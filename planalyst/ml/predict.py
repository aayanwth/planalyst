"""
PLanalyst — Prediction: League Winner via Monte Carlo Simulation

Loads the trained model, scores remaining fixtures for the 2026-27 season,
runs Monte Carlo simulation to compute title-winning probability per team.
Writes results to gold.gold_title_predictions.
"""

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from planalyst.config import (
    MODELS_DIR,
    SQLALCHEMY_CONNECTION_STRING,
    PL_SEASON,
    SCHEMA_BRONZE,
    SCHEMA_GOLD,
    DBT_GOLD_SCHEMA,
)
from planalyst.ml.features import canonicalize_team, load_live_features, load_team_name_map
from planalyst.ml.train import FEATURE_COLUMNS

N_SIMULATIONS = 1000  # Number of Monte Carlo simulations


def load_model():
    """Load the trained model and label encoder. Prefer local joblib (v2 XGBoost)."""
    import joblib

    model = joblib.load(MODELS_DIR / "match_predictor.joblib")
    print("  Model loaded from local file")
    try:
        label_encoder = joblib.load(MODELS_DIR / "label_encoder.joblib")
    except Exception:
        label_encoder = None
    return model, label_encoder


def load_remaining_fixtures(engine) -> pd.DataFrame:
    """Load fixtures that haven't been played yet from bronze."""
    query = text(f"""
        SELECT
            id, matchday,
            home_team_name, away_team_name,
            home_team_short, away_team_short
        FROM {SCHEMA_BRONZE}.raw_matches
        WHERE status != 'FINISHED'
          AND season = :season
        ORDER BY matchday
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"season": PL_SEASON})
    mapping = load_team_name_map()
    df["home_team_name"] = df["home_team_name"].map(lambda n: canonicalize_team(n, mapping))
    df["away_team_name"] = df["away_team_name"].map(lambda n: canonicalize_team(n, mapping))
    return df


def load_current_standings(engine) -> pd.DataFrame:
    """Load current cumulative standings from the gold fact table."""
    query = text(f"""
        SELECT
            team_name AS team,
            MAX(matchweek_number) AS last_matchweek,
            MAX(cumulative_points) AS current_points,
            MAX(cumulative_gd) AS current_gd
        FROM {DBT_GOLD_SCHEMA}.fact_team_sentiment_performance
        GROUP BY team_name
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    return df


def build_fixture_features(
    fixture: pd.Series,
    live_features: pd.DataFrame,
    is_home: bool = True,
) -> np.ndarray:
    """
    Build feature vector for a fixture using the latest available features
    for the team. Elo differential is computed vs the opponent.
    """
    team = fixture["home_team_name"] if is_home else fixture["away_team_name"]
    opponent = fixture["away_team_name"] if is_home else fixture["home_team_name"]

    team_data = live_features[live_features["team"] == team]
    opp_data = live_features[live_features["team"] == opponent]

    defaults = {
        "rolling_points_5": 5.0,
        "rolling_gd_5": 0.0,
        "season_points": 0.0,
        "season_gd": 0.0,
        "season_position": 10.0,
        "is_home": 1.0 if is_home else 0.0,
        "win_rate": 0.33,
        "games_played": 1.0,
        "elo_rating": 1500.0,
        "elo_diff": 0.0,
        "rolling_goals_for_5": 1.0,
        "rolling_goals_against_5": 1.0,
        "recent_win_streak": 0.0,
    }

    latest = team_data.iloc[-1] if not team_data.empty else pd.Series(defaults)
    opp_elo = float(opp_data.iloc[-1]["elo_rating"]) if not opp_data.empty and "elo_rating" in opp_data.columns else 1500.0
    team_elo = float(latest["elo_rating"]) if "elo_rating" in latest.index and pd.notna(latest["elo_rating"]) else 1500.0

    feature_values = []
    for col in FEATURE_COLUMNS:
        if col == "is_home":
            feature_values.append(1.0 if is_home else 0.0)
        elif col == "elo_diff":
            feature_values.append(team_elo - opp_elo)
        elif col in latest.index and pd.notna(latest[col]):
            feature_values.append(float(latest[col]))
        else:
            feature_values.append(float(defaults.get(col, 0.0)))

    return np.array(feature_values)


def _proba_from_perspective(model, features, label_encoder) -> dict[str, float]:
    """Return P(D), P(L), P(W) for the team whose features were used."""
    try:
        proba = model.predict_proba(features.reshape(1, -1))[0]
        classes = model.classes_
    except Exception as e:
        print(f"  [Predict] WARNING: model scoring failed, using prior probabilities: {e}")
        return {"D": 0.25, "L": 0.35, "W": 0.40}

    if label_encoder is not None:
        labels = [str(c).upper() for c in label_encoder.inverse_transform(list(classes))]
    else:
        labels = [str(c).upper() for c in classes]

    out = {"D": 0.0, "L": 0.0, "W": 0.0}
    for label, p in zip(labels, proba):
        if label in out:
            out[label] = float(p)
        elif label in {"2", "WIN"}:
            out["W"] = float(p)
        elif label in {"0", "DRAW"}:
            out["D"] = float(p)
        else:
            out["L"] = float(p)
    return out


def _home_away_draw_probs(model, fixture, live_features, label_encoder) -> np.ndarray:
    """Blend home- and away-view model outputs into [P(home win), P(draw), P(away win)]."""
    home_view = _proba_from_perspective(
        model, build_fixture_features(fixture, live_features, is_home=True), label_encoder
    )
    away_view = _proba_from_perspective(
        model, build_fixture_features(fixture, live_features, is_home=False), label_encoder
    )
    p_home = (home_view["W"] + away_view["L"]) / 2
    p_draw = (home_view["D"] + away_view["D"]) / 2
    p_away = (home_view["L"] + away_view["W"]) / 2
    model_probs = np.array([p_home, p_draw, p_away], dtype=float)
    if model_probs.sum() <= 0:
        model_probs = np.array([0.45, 0.25, 0.30])
    else:
        model_probs = model_probs / model_probs.sum()

    # Mix in Elo expected result so title odds track team strength, not just noise
    latest_elo = (
        live_features.sort_values("matchday").groupby("team")["elo_rating"].last()
        if not live_features.empty and "elo_rating" in live_features.columns
        else pd.Series(dtype=float)
    )
    home_elo = float(latest_elo.get(fixture["home_team_name"], 1500.0))
    away_elo = float(latest_elo.get(fixture["away_team_name"], 1500.0))
    exp_home = 1 / (1 + 10 ** ((away_elo - home_elo) / 400))
    p_elo_draw = 0.26
    elo_probs = np.array([
        (1 - p_elo_draw) * exp_home,
        p_elo_draw,
        (1 - p_elo_draw) * (1 - exp_home),
    ])
    blended = 0.4 * model_probs + 0.6 * elo_probs
    return blended / blended.sum()


def simulate_season(
    model,
    remaining_fixtures: pd.DataFrame,
    current_standings: pd.DataFrame,
    live_features: pd.DataFrame,
    n_simulations: int = N_SIMULATIONS,
    label_encoder=None,
) -> pd.DataFrame:
    """
    Monte Carlo simulation of the remaining season.

    For each remaining fixture:
    - Predict P(Home Win), P(Draw), P(Away Win)
    - Sample outcome according to those probabilities
    - Accumulate points

    Returns: DataFrame with team, win_probability, avg_final_points, avg_final_rank
    """
    print(f"  Running {n_simulations} Monte Carlo simulations...")

    columns = ["team_name", "win_probability", "avg_final_points", "avg_final_rank",
               "simulations_won", "total_simulations"]
    if current_standings.empty:
        print("  No standings yet (no finished matches); skipping simulation.")
        return pd.DataFrame(columns=columns)

    teams = current_standings["team"].tolist()
    base_points = dict(zip(current_standings["team"], current_standings["current_points"]))
    base_gd = dict(zip(current_standings["team"], current_standings["current_gd"]))

    title_wins = {team: 0 for team in teams}
    total_points_sum = {team: 0.0 for team in teams}
    total_rank_sum = {team: 0.0 for team in teams}

    # Pre-compute predictions for all fixtures
    fixture_predictions = []
    for _, fixture in remaining_fixtures.iterrows():
        fixture_predictions.append({
            "home_team": fixture["home_team_name"],
            "away_team": fixture["away_team_name"],
            "proba": _home_away_draw_probs(model, fixture, live_features, label_encoder),
        })

    # Run simulations
    rng = np.random.default_rng()
    margins = np.array([1, 1, 1, 2, 2, 3])  # typical winning goal margins

    for sim in range(n_simulations):
        sim_points = dict(base_points)
        sim_gd = dict(base_gd)

        for fp in fixture_predictions:
            outcome_idx = rng.choice(3, p=fp["proba"])
            if outcome_idx == 0:
                home_pts, away_pts = 3, 0
                margin = int(rng.choice(margins))
            elif outcome_idx == 1:
                home_pts, away_pts = 1, 1
                margin = 0
            else:
                home_pts, away_pts = 0, 3
                margin = -int(rng.choice(margins))

            # Keep goal difference moving so tiebreaks reflect simulated results
            if fp["home_team"] in sim_gd:
                sim_gd[fp["home_team"]] += margin
            if fp["away_team"] in sim_gd:
                sim_gd[fp["away_team"]] -= margin

            if fp["home_team"] in sim_points:
                sim_points[fp["home_team"]] += home_pts
            if fp["away_team"] in sim_points:
                sim_points[fp["away_team"]] += away_pts

        # Determine final standings
        standings = sorted(
            sim_points.items(),
            key=lambda x: (x[1], sim_gd.get(x[0], 0)),
            reverse=True,
        )

        # Record who won the title
        if standings:
            title_winner = standings[0][0]
            title_wins[title_winner] += 1

        # Record points and ranks
        for rank, (team, pts) in enumerate(standings, 1):
            total_points_sum[team] += pts
            total_rank_sum[team] += rank

    # Build results
    results = []
    for team in teams:
        results.append({
            "team_name": team,
            "win_probability": round(title_wins[team] / n_simulations, 4),
            "avg_final_points": round(total_points_sum[team] / n_simulations, 1),
            "avg_final_rank": round(total_rank_sum[team] / n_simulations, 1),
            "simulations_won": title_wins[team],
            "total_simulations": n_simulations,
        })

    return pd.DataFrame(results).sort_values("win_probability", ascending=False)


def run_predictions(current_matchweek: int | None = None) -> pd.DataFrame:
    """
    Main entry point: load model, get fixtures, simulate, write predictions.
    """
    print("\n[Predict] Running title prediction pipeline...")

    engine = create_engine(SQLALCHEMY_CONNECTION_STRING)

    # Load model
    model, label_encoder = load_model()

    # Load current state
    remaining = load_remaining_fixtures(engine)
    print(f"  Remaining fixtures: {len(remaining)}")

    standings = load_current_standings(engine)
    print(f"  Teams with standings: {len(standings)}")

    if current_matchweek is None:
        current_matchweek = int(standings["last_matchweek"].max()) if not standings.empty else 0
    print(f"  Current matchweek: {current_matchweek}")

    # Load live features
    live_features = load_live_features()

    if standings.empty:
        print("  No finished matches yet - nothing to predict.")
        return pd.DataFrame()

    # Simulate
    predictions = simulate_season(
        model, remaining, standings, live_features, label_encoder=label_encoder
    )

    # Add metadata
    predictions["matchweek"] = current_matchweek
    predictions["season"] = PL_SEASON
    predictions["model_version"] = "xgb_v2"

    # Verify probabilities sum to ~1.0
    total_prob = predictions["win_probability"].sum()
    print(f"\n  Total win probability: {total_prob:.4f} (should be ~1.0)")

    # Write to gold
    predictions.to_sql(
        "gold_title_predictions",
        engine,
        schema=SCHEMA_GOLD,
        if_exists="replace",
        index=False,
    )
    print(f"  Written to {SCHEMA_GOLD}.gold_title_predictions")

    # Print top predictions
    print(f"\n  --- Title Predictions (Matchweek {current_matchweek}) ---")
    for _, row in predictions.head(10).iterrows():
        bar = "█" * int(row["win_probability"] * 100)
        print(f"    {row['team_name']:25s} {row['win_probability']:6.1%} {bar}")

    return predictions


if __name__ == "__main__":
    run_predictions()
