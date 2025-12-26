"""
PLanalyst — Feature Engineering for Predictive Model

Computes per-team-per-matchweek features from historical match data
for training the league winner prediction model.

Features:
- Rolling form (points from last 5 games)
- Goal difference trend (last 5 games)
- Home/away split win rate
- Season position at matchweek N
"""

from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

from planalyst.config import (
    DBT_GOLD_SCHEMA,
    PROJECT_ROOT,
    SCHEMA_TRAINING,
    SQLALCHEMY_CONNECTION_STRING,
)
from planalyst.ml.elo import DEFAULT_ELO


def load_team_name_map() -> dict[str, str]:
    """Map API / news / short names to the canonical names used in Gold."""
    seed = Path(PROJECT_ROOT) / "dbt_project" / "seeds" / "team_name_lookup.csv"
    lookup = pd.read_csv(seed)
    mapping: dict[str, str] = {}
    for _, row in lookup.iterrows():
        mapping[str(row["api_name"])] = str(row["canonical_name"])
        mapping[str(row["news_name"])] = str(row["canonical_name"])
        mapping[str(row["canonical_name"])] = str(row["canonical_name"])
    return mapping


def canonicalize_team(name: str, mapping: dict[str, str] | None = None) -> str:
    mapping = mapping or load_team_name_map()
    return mapping.get(name, name)


def load_historical_data(engine) -> pd.DataFrame:
    """Load historical match data from the training schema."""
    query = text("""
        SELECT
            id, matchday, season, season_label,
            home_team_name, away_team_name,
            score_home, score_away, score_winner
        FROM training.historical_matches
        WHERE score_home IS NOT NULL
        ORDER BY season, matchday
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn)
    return df


def unpivot_to_team_level(df: pd.DataFrame) -> pd.DataFrame:
    """Convert match-level data to team-level (one row per team per match)."""
    home = df.copy()
    home["team"] = home["home_team_name"]
    home["opponent"] = home["away_team_name"]
    home["goals_for"] = home["score_home"]
    home["goals_against"] = home["score_away"]
    home["is_home"] = 1
    home["points"] = home.apply(
        lambda r: 3 if r["score_home"] > r["score_away"]
        else (1 if r["score_home"] == r["score_away"] else 0), axis=1
    )
    home["result"] = home.apply(
        lambda r: "W" if r["score_home"] > r["score_away"]
        else ("D" if r["score_home"] == r["score_away"] else "L"), axis=1
    )

    away = df.copy()
    away["team"] = away["away_team_name"]
    away["opponent"] = away["home_team_name"]
    away["goals_for"] = away["score_away"]
    away["goals_against"] = away["score_home"]
    away["is_home"] = 0
    away["points"] = away.apply(
        lambda r: 3 if r["score_away"] > r["score_home"]
        else (1 if r["score_away"] == r["score_home"] else 0), axis=1
    )
    away["result"] = away.apply(
        lambda r: "W" if r["score_away"] > r["score_home"]
        else ("D" if r["score_away"] == r["score_home"] else "L"), axis=1
    )

    cols = ["id", "season", "season_label", "matchday", "team", "opponent",
            "goals_for", "goals_against", "is_home", "points", "result"]
    return pd.concat([home[cols], away[cols]], ignore_index=True).sort_values(
        ["season", "matchday", "team"]
    )


def compute_features(team_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute rolling features per team per season.

    Features:
    - rolling_points_5: sum of points from last 5 matches
    - rolling_gd_5: sum of goal difference from last 5 matches
    - season_points: cumulative points in this season so far
    - season_gd: cumulative GD in this season so far
    - season_position: league position at this matchweek
    - home_win_rate: % of home games won this season
    - away_win_rate: % of away games won this season
    """
    features = []

    for (season, team), group in team_df.groupby(["season", "team"]):
        group = group.sort_values("matchday").reset_index(drop=True)

        group["gd"] = group["goals_for"] - group["goals_against"]
        group["rolling_points_5"] = group["points"].rolling(5, min_periods=1).sum()
        group["rolling_gd_5"] = group["gd"].rolling(5, min_periods=1).sum()
        group["season_points"] = group["points"].cumsum()
        group["season_gd"] = group["gd"].cumsum()
        group["season_goals_for"] = group["goals_for"].cumsum()
        group["season_goals_against"] = group["goals_against"].cumsum()

        group["games_played"] = range(1, len(group) + 1)

        # Win indicator
        group["is_win"] = (group["result"] == "W").astype(int)
        group["win_rate"] = group["is_win"].expanding().mean()

        features.append(group)

    result = pd.concat(features, ignore_index=True)

    # Compute season position per matchweek
    position_dfs = []
    for (season, matchday), mw_group in result.groupby(["season", "matchday"]):
        mw_sorted = mw_group.sort_values(
            ["season_points", "season_gd", "season_goals_for"],
            ascending=[False, False, False]
        )
        mw_sorted["season_position"] = range(1, len(mw_sorted) + 1)
        position_dfs.append(mw_sorted)

    return pd.concat(position_dfs, ignore_index=True)


def compute_target(features_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add target variable: did the team win the next match?
    For per-match prediction training.
    """
    df = features_df.sort_values(["season", "team", "matchday"]).copy()

    # Target: next match result (shifted forward within same team+season)
    df["next_result"] = df.groupby(["season", "team"])["result"].shift(-1)
    df["target_win"] = (df["next_result"] == "W").astype(int)
    df["target_draw"] = (df["next_result"] == "D").astype(int)
    df["target_loss"] = (df["next_result"] == "L").astype(int)

    # Drop last matchday per season (no next match to predict)
    df = df.dropna(subset=["next_result"])

    return df


def build_feature_frame(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Pure step: raw match rows -> team-level rows with rolling features and next-match targets."""
    team_df = unpivot_to_team_level(raw_df)
    features_df = compute_features(team_df)
    return compute_target(features_df)


def build_training_features() -> pd.DataFrame:
    """Full pipeline: load data -> unpivot -> compute features -> add targets."""
    print("[Features] Building training feature set...")
    engine = create_engine(SQLALCHEMY_CONNECTION_STRING)

    raw_df = load_historical_data(engine)
    print(f"  Loaded {len(raw_df)} historical matches")

    if raw_df.empty:
        print("  No historical data found. Run historical_matches pipeline first.")
        return pd.DataFrame()

    training_df = build_feature_frame(raw_df)
    print(f"  Final training set: {len(training_df)} rows")

    # Write to training schema
    training_df.to_sql(
        "training_features",
        engine,
        schema=SCHEMA_TRAINING,
        if_exists="replace",
        index=False,
    )
    print(f"  Written to {SCHEMA_TRAINING}.training_features")

    return training_df


def load_played_matches(engine) -> pd.DataFrame:
    """
    Every finished match we know about: training history plus the live season, with team names
    canonicalised so they line up with the Gold tables and the remaining fixtures.
    """
    mapping = load_team_name_map()
    cols = "season, matchday, home_team_name, away_team_name, score_home, score_away"
    with engine.connect() as conn:
        hist = pd.read_sql(
            text(f"SELECT {cols} FROM training.historical_matches WHERE score_home IS NOT NULL"),
            conn,
        )
        live = pd.read_sql(
            text(
                f"SELECT {cols} FROM bronze.raw_matches "
                "WHERE status = 'FINISHED' AND score_home IS NOT NULL"
            ),
            conn,
        )
    matches = pd.concat([hist, live], ignore_index=True)
    for col in ("home_team_name", "away_team_name"):
        matches[col] = matches[col].map(lambda n: canonicalize_team(n, mapping))
    return matches


def load_live_features() -> pd.DataFrame:
    """Load current season features from the gold fact table for scoring."""
    engine = create_engine(SQLALCHEMY_CONNECTION_STRING)

    query = text(f"""
        SELECT
            team_name AS team,
            matchweek_number AS matchday,
            result,
            goals_for,
            goals_against,
            points,
            goal_difference AS gd,
            cumulative_points AS season_points,
            cumulative_gd AS season_gd,
            avg_sentiment_score,
            article_count
        FROM {DBT_GOLD_SCHEMA}.fact_team_sentiment_performance
        ORDER BY team_name, matchweek_number
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    if df.empty:
        return df

    # Compute rolling features matching training data
    features = []
    for team, group in df.groupby("team"):
        group = group.sort_values("matchday").reset_index(drop=True)
        group["rolling_points_5"] = group["points"].rolling(5, min_periods=1).sum()
        group["rolling_gd_5"] = group["gd"].rolling(5, min_periods=1).sum()
        group["rolling_goals_for_5"] = group["goals_for"].rolling(5, min_periods=1).mean()
        group["rolling_goals_against_5"] = group["goals_against"].rolling(5, min_periods=1).mean()
        group["is_home"] = 0.5  # overridden per fixture in predict.py
        group["win_rate"] = (group["result"] == "W").expanding().mean()
        group["games_played"] = range(1, len(group) + 1)
        group["season_goals_for"] = group["goals_for"].cumsum()
        group["season_goals_against"] = group["goals_against"].cumsum()

        streak = []
        current_streak = 0
        for result in group["result"]:
            if result == "W":
                current_streak += 1
            else:
                current_streak = 0
            streak.append(current_streak)
        group["recent_win_streak"] = streak
        features.append(group)

    result = pd.concat(features, ignore_index=True)

    # Compute position
    position_dfs = []
    for matchday, mw_group in result.groupby("matchday"):
        mw_sorted = mw_group.sort_values(
            ["season_points", "season_gd", "season_goals_for"],
            ascending=[False, False, False]
        )
        mw_sorted["season_position"] = range(1, len(mw_sorted) + 1)
        position_dfs.append(mw_sorted)

    result = pd.concat(position_dfs, ignore_index=True)

    # Current Elo from historical + live finished matches (canonical names). A failure here
    # must surface: silently defaulting every team to the same rating gives meaningless odds.
    from planalyst.ml.train import compute_elo_ratings

    elo = compute_elo_ratings(load_played_matches(engine))
    result["elo_rating"] = result["team"].map(lambda t: elo.get(t, DEFAULT_ELO))
    result["elo_diff"] = 0.0  # overridden per fixture in predict.py

    return result


if __name__ == "__main__":
    df = build_training_features()
    if not df.empty:
        print("\nSample of training features:")
        print(df[["season", "team", "matchday", "rolling_points_5", "season_position", "next_result"]].head(20))
