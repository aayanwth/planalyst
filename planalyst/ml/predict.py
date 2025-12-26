"""
PLanalyst — Prediction: fixture probabilities and a Monte Carlo title race.

Every remaining fixture gets [P(home win), P(draw), P(away win)] from an equal-weight blend of
three independent estimates:

  xgb      the XGBoost match model (both teams' views averaged so it is symmetric)
  elo      Elo expectation incl. home advantage (planalyst.ml.elo)
  poisson  independent-Poisson goals model (planalyst.ml.poisson)

The blend is not tuned: on validation seasons every blend with real weight on the components
was within ~0.001 log loss of the best one (see docs/model_evaluation.md), so equal weights
avoid fitting noise. Those probabilities then drive a vectorised Monte Carlo of the rest of the
season. Winning margins are sampled from the empirical distribution of past results so
goal-difference tiebreaks are realistic.

Outputs (Gold schema)
  gold_title_predictions      latest run: title / top-4 / relegation probability, points range
  title_prediction_history    append-only, one set of rows per scored matchweek
  fixture_predictions         the forecast for each upcoming match, frozen once it kicks off so
                              live accuracy can be scored against what was predicted beforehand
"""

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, inspect, text

from planalyst.config import (
    DBT_GOLD_SCHEMA,
    MODELS_DIR,
    PL_SEASON,
    SCHEMA_BRONZE,
    SCHEMA_GOLD,
    SQLALCHEMY_CONNECTION_STRING,
)
from planalyst.ml.elo import outcome_probs as elo_outcome_probs
from planalyst.ml.features import (
    canonicalize_team,
    load_live_features,
    load_played_matches,
    load_team_name_map,
)
from planalyst.ml.poisson import PoissonGoalModel
from planalyst.ml.train import FEATURE_COLUMNS

N_SIMULATIONS = 1000  # Number of Monte Carlo simulations
MODEL_VERSION = "blend_v3"
BLEND_WEIGHTS = {"xgb": 1 / 3, "elo": 1 / 3, "poisson": 1 / 3}
RELEGATION_PLACES = 3
# Fallback winning margins when no historical results are available (tests, empty DB).
DEFAULT_MARGINS = np.array([1, 1, 1, 2, 2, 3])


def load_model():
    """Load the trained model and label encoder. Prefer local joblib (v2 XGBoost)."""
    import joblib

    model_path = MODELS_DIR / "match_predictor.joblib"
    if not model_path.exists():
        raise FileNotFoundError(
            f"No trained model at {model_path}. Train one first: run the `model_training_job` "
            "Dagster job or `python -m planalyst.ml.train`."
        )
    model = joblib.load(model_path)
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
            id, matchday, utc_date,
            home_team_name, away_team_name,
            home_team_short, away_team_short
        FROM {SCHEMA_BRONZE}.raw_matches
        WHERE status != 'FINISHED'
          AND season = :season
        ORDER BY matchday, utc_date
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


def empirical_margins(matches: pd.DataFrame) -> np.ndarray:
    """Winning margins (goal difference of decisive matches) observed in `matches`."""
    gd = (matches["score_home"] - matches["score_away"]).abs().to_numpy()
    margins = gd[gd > 0].astype(int)
    return margins if len(margins) else DEFAULT_MARGINS


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


def blend_probs(
    components: dict[str, np.ndarray], weights: dict[str, float] | None = None
) -> np.ndarray:
    """Weighted mix of probability arrays (last axis = home/draw/away), renormalised to sum to 1."""
    weights = BLEND_WEIGHTS if weights is None else weights
    total = sum(w * np.asarray(components[name], dtype=float) for name, w in weights.items())
    return total / total.sum(axis=-1, keepdims=True)


def model_and_elo_probs(
    model, fixture, live_features, label_encoder
) -> tuple[np.ndarray, np.ndarray]:
    """Return (XGBoost probs, Elo probs) as [P(home win), P(draw), P(away win)] each."""
    home_view = _proba_from_perspective(
        model, build_fixture_features(fixture, live_features, is_home=True), label_encoder
    )
    away_view = _proba_from_perspective(
        model, build_fixture_features(fixture, live_features, is_home=False), label_encoder
    )
    # Each team's view of the same match is averaged so the result is symmetric.
    model_probs = np.array(
        [
            (home_view["W"] + away_view["L"]) / 2,
            (home_view["D"] + away_view["D"]) / 2,
            (home_view["L"] + away_view["W"]) / 2,
        ],
        dtype=float,
    )
    if model_probs.sum() <= 0:
        model_probs = np.array([0.45, 0.25, 0.30])
    else:
        model_probs = model_probs / model_probs.sum()

    latest_elo = (
        live_features.sort_values("matchday").groupby("team")["elo_rating"].last()
        if not live_features.empty and "elo_rating" in live_features.columns
        else pd.Series(dtype=float)
    )
    home_elo = float(latest_elo.get(fixture["home_team_name"], 1500.0))
    away_elo = float(latest_elo.get(fixture["away_team_name"], 1500.0))
    return model_probs, elo_outcome_probs(home_elo, away_elo)


def fixture_components(
    model,
    fixtures: pd.DataFrame,
    live_features: pd.DataFrame,
    label_encoder,
    goals_model: PoissonGoalModel,
) -> dict[str, np.ndarray]:
    """Per-component (F, 3) probability arrays for every fixture, keyed like BLEND_WEIGHTS."""
    if fixtures.empty:
        empty = np.zeros((0, 3))
        return {"xgb": empty, "elo": empty, "poisson": empty}
    pairs = [
        model_and_elo_probs(model, fx, live_features, label_encoder)
        for _, fx in fixtures.iterrows()
    ]
    return {
        "xgb": np.array([p[0] for p in pairs]),
        "elo": np.array([p[1] for p in pairs]),
        "poisson": goals_model.outcome_probs(
            fixtures["home_team_name"].tolist(), fixtures["away_team_name"].tolist()
        ),
    }


def score_fixtures(
    model,
    fixtures: pd.DataFrame,
    live_features: pd.DataFrame,
    label_encoder,
    goals_model: PoissonGoalModel,
    weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """`fixtures` plus blended p_home / p_draw / p_away columns."""
    comps = fixture_components(model, fixtures, live_features, label_encoder, goals_model)
    blended = blend_probs(comps, weights).reshape(-1, 3)
    out = fixtures.copy()
    out["p_home"], out["p_draw"], out["p_away"] = blended[:, 0], blended[:, 1], blended[:, 2]
    return out


def simulate_title_race(
    home_idx: np.ndarray,
    away_idx: np.ndarray,
    fixture_probs: np.ndarray,
    base_points: np.ndarray,
    base_gd: np.ndarray,
    n_simulations: int = N_SIMULATIONS,
    seed: int | None = None,
    margins: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """
    Vectorised Monte Carlo over the remaining fixtures.

    home_idx / away_idx index into the team arrays; fixture_probs is (F, 3) of
    [P(home win), P(draw), P(away win)]; `margins` is the pool winning goal margins are drawn
    from. Ties on points are broken by simulated goal difference.

    Returns title_counts, avg_points / avg_rank, points_p10 / points_p90 and rank_counts, a
    (teams x positions) matrix of how often each team finished in each place.
    """
    rng = np.random.default_rng(seed)
    pool = DEFAULT_MARGINS if margins is None or len(margins) == 0 else np.asarray(margins)
    n_teams = len(base_points)
    n_fix = len(home_idx)

    draws = rng.random((n_simulations, n_fix))
    cum = np.cumsum(fixture_probs, axis=1)
    outcome = (draws[:, :, None] > cum[None, :, :2]).sum(axis=2)  # 0=home, 1=draw, 2=away
    margin = rng.choice(pool, size=(n_simulations, n_fix))

    home_pts = np.select([outcome == 0, outcome == 1], [3, 1], default=0)
    away_pts = np.select([outcome == 2, outcome == 1], [3, 1], default=0)
    home_gd = np.select([outcome == 0, outcome == 2], [margin, -margin], default=0)

    home_onehot = np.zeros((n_fix, n_teams))
    away_onehot = np.zeros((n_fix, n_teams))
    home_onehot[np.arange(n_fix), home_idx] = 1
    away_onehot[np.arange(n_fix), away_idx] = 1

    points = base_points[None, :] + home_pts @ home_onehot + away_pts @ away_onehot
    gd = base_gd[None, :] + home_gd @ home_onehot - home_gd @ away_onehot

    order = np.argsort(-(points * 10_000 + gd), axis=1, kind="stable")
    ranks = np.empty_like(order)
    rows = np.arange(n_simulations)[:, None]
    ranks[rows, order] = np.arange(1, n_teams + 1)[None, :]

    rank_counts = np.stack(
        [np.bincount(ranks[:, t] - 1, minlength=n_teams) for t in range(n_teams)]
    )
    return {
        "title_counts": np.bincount(order[:, 0], minlength=n_teams),
        "avg_points": points.mean(axis=0),
        "avg_rank": ranks.mean(axis=0),
        "points_p10": np.percentile(points, 10, axis=0),
        "points_p90": np.percentile(points, 90, axis=0),
        "rank_counts": rank_counts,
    }


PREDICTION_COLUMNS = [
    "team_name", "win_probability", "avg_final_points", "avg_final_rank", "simulations_won",
    "total_simulations", "top4_probability", "relegation_probability", "points_p10", "points_p90",
]  # fmt: skip


def simulate_season(
    remaining_fixtures: pd.DataFrame,
    current_standings: pd.DataFrame,
    n_simulations: int = N_SIMULATIONS,
    seed: int | None = None,
    margins: np.ndarray | None = None,
) -> pd.DataFrame:
    """
    Monte Carlo simulation of the remaining season.

    `remaining_fixtures` must already carry p_home / p_draw / p_away (see `score_fixtures`);
    outcomes are sampled and points and goal difference accumulated.
    """
    print(f"  Running {n_simulations} Monte Carlo simulations...")

    if current_standings.empty:
        print("  No standings yet (no finished matches); skipping simulation.")
        return pd.DataFrame(columns=PREDICTION_COLUMNS)

    teams = current_standings["team"].tolist()
    team_idx = {t: i for i, t in enumerate(teams)}
    base_points = current_standings["current_points"].to_numpy(dtype=float)
    base_gd = current_standings["current_gd"].to_numpy(dtype=float)

    known = remaining_fixtures[
        remaining_fixtures["home_team_name"].isin(team_idx)
        & remaining_fixtures["away_team_name"].isin(team_idx)
    ]
    home_idx = known["home_team_name"].map(team_idx).to_numpy(dtype=int)
    away_idx = known["away_team_name"].map(team_idx).to_numpy(dtype=int)
    fixture_probs = known[["p_home", "p_draw", "p_away"]].to_numpy(dtype=float).reshape(-1, 3)

    sim = simulate_title_race(
        home_idx, away_idx, fixture_probs, base_points, base_gd, n_simulations, seed, margins
    )
    counts = sim["rank_counts"]
    n_teams = len(teams)
    relegation = min(RELEGATION_PLACES, n_teams)

    results = pd.DataFrame(
        {
            "team_name": teams,
            "win_probability": np.round(sim["title_counts"] / n_simulations, 4),
            "avg_final_points": np.round(sim["avg_points"], 1),
            "avg_final_rank": np.round(sim["avg_rank"], 1),
            "simulations_won": sim["title_counts"],
            "total_simulations": n_simulations,
            "top4_probability": np.round(counts[:, :4].sum(axis=1) / n_simulations, 4),
            "relegation_probability": np.round(counts[:, n_teams - relegation :].sum(axis=1) / n_simulations, 4),
            "points_p10": np.round(sim["points_p10"], 1),
            "points_p90": np.round(sim["points_p90"], 1),
        }
    )
    return results.sort_values("win_probability", ascending=False)


# ── Persistence ──────────────────────────────────────────────────────────────
HISTORY_TABLE = "title_prediction_history"
HISTORY_DDL = f"""
    CREATE TABLE IF NOT EXISTS {SCHEMA_GOLD}.{HISTORY_TABLE} (
        season INTEGER NOT NULL,
        matchweek INTEGER NOT NULL,
        model_version TEXT NOT NULL,
        team_name TEXT NOT NULL,
        win_probability DOUBLE PRECISION,
        avg_final_points DOUBLE PRECISION,
        avg_final_rank DOUBLE PRECISION,
        simulations_won INTEGER,
        total_simulations INTEGER,
        scored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (season, matchweek, model_version, team_name)
    )
"""
# Columns added after the table first shipped; existing databases are migrated in place.
HISTORY_ADDED_COLUMNS = {
    "top4_probability": "DOUBLE PRECISION",
    "relegation_probability": "DOUBLE PRECISION",
    "points_p10": "DOUBLE PRECISION",
    "points_p90": "DOUBLE PRECISION",
}
HISTORY_COLUMNS = [
    "season", "matchweek", "model_version", "team_name", "win_probability",
    "avg_final_points", "avg_final_rank", "simulations_won", "total_simulations",
    *HISTORY_ADDED_COLUMNS,
]  # fmt: skip

FIXTURE_TABLE = "fixture_predictions"
FIXTURE_DDL = f"""
    CREATE TABLE IF NOT EXISTS {SCHEMA_GOLD}.{FIXTURE_TABLE} (
        match_id BIGINT PRIMARY KEY,
        season INTEGER NOT NULL,
        matchday INTEGER,
        utc_date TIMESTAMPTZ,
        home_team_name TEXT NOT NULL,
        away_team_name TEXT NOT NULL,
        p_home DOUBLE PRECISION NOT NULL,
        p_draw DOUBLE PRECISION NOT NULL,
        p_away DOUBLE PRECISION NOT NULL,
        model_version TEXT NOT NULL,
        predicted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""
FIXTURE_COLUMNS = [
    "match_id", "season", "matchday", "utc_date", "home_team_name", "away_team_name",
    "p_home", "p_draw", "p_away", "model_version",
]  # fmt: skip


def _add_missing_columns(conn, table: str, columns: dict[str, str]) -> None:
    """ALTER TABLE ... ADD COLUMN for any column the live table lacks (portable, idempotent)."""
    existing = {c["name"] for c in inspect(conn).get_columns(table, schema=SCHEMA_GOLD)}
    for name, sql_type in columns.items():
        if name not in existing:
            conn.execute(text(f"ALTER TABLE {SCHEMA_GOLD}.{table} ADD COLUMN {name} {sql_type}"))


def record_history(engine, predictions: pd.DataFrame) -> int:
    """
    Append this run to the history table (gold_title_predictions only keeps the latest run).

    Re-running the same season / matchweek / model version replaces its rows, so the
    pipeline stays idempotent. Returns the number of rows written.
    """
    if predictions.empty:
        return 0
    key = predictions.iloc[0]
    with engine.begin() as conn:
        conn.execute(text(HISTORY_DDL))
        _add_missing_columns(conn, HISTORY_TABLE, HISTORY_ADDED_COLUMNS)
        conn.execute(
            text(
                f"DELETE FROM {SCHEMA_GOLD}.{HISTORY_TABLE} WHERE season = :season "
                "AND matchweek = :matchweek AND model_version = :model_version"
            ),
            {
                "season": int(key["season"]),
                "matchweek": int(key["matchweek"]),
                "model_version": str(key["model_version"]),
            },
        )
        predictions[HISTORY_COLUMNS].to_sql(
            HISTORY_TABLE, conn, schema=SCHEMA_GOLD, if_exists="append", index=False
        )
    return len(predictions)


def record_fixture_predictions(
    engine, scored: pd.DataFrame, season: int, model_version: str = MODEL_VERSION
) -> int:
    """
    Store the forecast for every unplayed fixture in `scored`.

    Rows for these match ids are replaced (the forecast is refreshed until kick-off); rows for
    matches no longer in `scored` — i.e. already played — are left untouched, which freezes
    the last pre-match forecast so accuracy is judged on what was known beforehand.
    """
    if scored.empty:
        return 0
    rows = pd.DataFrame(
        {
            "match_id": scored["id"].astype("int64"),
            "season": season,
            "matchday": scored["matchday"].astype("int64"),
            "utc_date": pd.to_datetime(scored["utc_date"], utc=True).map(
                lambda d: None if pd.isna(d) else d.isoformat()
            ),
            "home_team_name": scored["home_team_name"],
            "away_team_name": scored["away_team_name"],
            "p_home": scored["p_home"],
            "p_draw": scored["p_draw"],
            "p_away": scored["p_away"],
            "model_version": model_version,
        }
    )[FIXTURE_COLUMNS]
    with engine.begin() as conn:
        conn.execute(text(FIXTURE_DDL))
        conn.execute(
            text(f"DELETE FROM {SCHEMA_GOLD}.{FIXTURE_TABLE} WHERE match_id = :id"),
            [{"id": int(i)} for i in rows["match_id"]],
        )
        rows.to_sql(FIXTURE_TABLE, conn, schema=SCHEMA_GOLD, if_exists="append", index=False)
    return len(rows)


def run_predictions(current_matchweek: int | None = None) -> pd.DataFrame:
    """
    Main entry point: load models, score fixtures, simulate, write predictions.
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

    if standings.empty:
        print("  No finished matches yet - nothing to predict.")
        return pd.DataFrame()

    live_features = load_live_features()
    played = load_played_matches(engine)
    goals_model = PoissonGoalModel().fit(played)
    margins = empirical_margins(played)

    scored = score_fixtures(model, remaining, live_features, label_encoder, goals_model)
    predictions = simulate_season(scored, standings, margins=margins)

    # Add metadata
    predictions["matchweek"] = current_matchweek
    predictions["season"] = PL_SEASON
    predictions["model_version"] = MODEL_VERSION

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
    rows = record_history(engine, predictions)
    print(f"  Appended {rows} rows to {SCHEMA_GOLD}.{HISTORY_TABLE}")
    n_fixtures = record_fixture_predictions(engine, scored, PL_SEASON)
    print(f"  Stored {n_fixtures} fixture forecasts in {SCHEMA_GOLD}.{FIXTURE_TABLE}")

    # Print top predictions
    print(f"\n  --- Title Predictions (Matchweek {current_matchweek}) ---")
    for _, row in predictions.head(10).iterrows():
        bar = "#" * int(row["win_probability"] * 100)
        print(f"    {row['team_name']:25s} {row['win_probability']:6.1%} {bar}")

    return predictions


if __name__ == "__main__":
    run_predictions()
