"""
EPL Analytics — Data Transformers

Converts raw FPL API JSON responses into clean Pandas DataFrames
ready for loading into the MySQL Star Schema.
"""

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Element type mapping (FPL integer → position abbreviation)
# ---------------------------------------------------------------------------
ELEMENT_TYPE_MAP: dict[int, str] = {
    1: "GKP",
    2: "DEF",
    3: "MID",
    4: "FWD",
}


def transform_teams(bootstrap_data: dict) -> pd.DataFrame:
    """Extract and clean team dimension data from bootstrap-static response.

    Args:
        bootstrap_data: Full JSON response from /bootstrap-static/.

    Returns:
        DataFrame with columns matching dim_teams schema.
    """
    teams_raw = bootstrap_data.get("teams", [])
    if not teams_raw:
        logger.warning("No teams found in bootstrap data.")
        return pd.DataFrame()

    df = pd.DataFrame(teams_raw)
    df = df.rename(columns={
        "id": "team_id",
        "code": "team_code",
        "name": "team_name",
    })

    keep_cols = [
        "team_id", "team_code", "team_name", "short_name",
        "strength_overall_home", "strength_overall_away",
        "strength_attack_home", "strength_attack_away",
        "strength_defence_home", "strength_defence_away",
        "pulse_id",
    ]
    df = df[[c for c in keep_cols if c in df.columns]]
    logger.info("Transformed %d teams.", len(df))
    return df


def transform_players(bootstrap_data: dict) -> pd.DataFrame:
    """Extract and clean player dimension data from bootstrap-static response.

    Args:
        bootstrap_data: Full JSON response from /bootstrap-static/.

    Returns:
        DataFrame with columns matching dim_players schema.
    """
    elements_raw = bootstrap_data.get("elements", [])
    if not elements_raw:
        logger.warning("No players found in bootstrap data.")
        return pd.DataFrame()

    df = pd.DataFrame(elements_raw)
    df = df.rename(columns={
        "id": "player_id",
        "code": "player_code",
        "team": "team_id",
    })

    # Map element_type integer to position string
    df["position"] = df["element_type"].map(ELEMENT_TYPE_MAP).fillna("UNK")

    # Handle chance_of_playing (can be None)
    df["chance_of_playing"] = df.get(
        "chance_of_playing_next_round", pd.Series(dtype="object")
    )

    # Clean selected_by_percent and form to numeric
    for col in ["selected_by_percent", "form", "points_per_game"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    keep_cols = [
        "player_id", "player_code", "first_name", "second_name",
        "web_name", "team_id", "element_type", "position",
        "now_cost", "status", "chance_of_playing", "news",
        "total_points", "points_per_game", "selected_by_percent", "form",
    ]
    df = df[[c for c in keep_cols if c in df.columns]]

    # Truncate news to 255 chars to fit VARCHAR(255)
    if "news" in df.columns:
        df["news"] = df["news"].astype(str).str[:255].replace("", None)

    logger.info("Transformed %d players.", len(df))
    return df


def transform_fixtures(fixtures_data: list[dict]) -> pd.DataFrame:
    """Extract and clean fixture dimension data from /fixtures/ response.

    Args:
        fixtures_data: List of fixture dicts from the API.

    Returns:
        DataFrame with columns matching dim_fixtures schema.
    """
    if not fixtures_data:
        logger.warning("No fixtures found.")
        return pd.DataFrame()

    df = pd.DataFrame(fixtures_data)
    df = df.rename(columns={
        "id": "fixture_id",
        "code": "fixture_code",
        "event": "gameweek",
    })

    # Parse kickoff_time to datetime
    if "kickoff_time" in df.columns:
        df["kickoff_time"] = pd.to_datetime(
            df["kickoff_time"], errors="coerce", utc=True
        )
        # Strip timezone for MySQL DATETIME compatibility
        df["kickoff_time"] = df["kickoff_time"].dt.tz_localize(None)

    # Convert finished boolean
    df["finished"] = df["finished"].astype(int)

    keep_cols = [
        "fixture_id", "fixture_code", "gameweek", "kickoff_time",
        "team_h", "team_a", "team_h_score", "team_a_score",
        "team_h_difficulty", "team_a_difficulty", "finished",
    ]
    df = df[[c for c in keep_cols if c in df.columns]]

    logger.info("Transformed %d fixtures.", len(df))
    return df


def transform_player_gameweek(
    live_data: dict,
    gameweek: int,
    fixtures_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Flatten per-player live stats for a given gameweek.

    The /event/{gw}/live/ endpoint returns:
        { "elements": [ { "id": 1, "stats": { ... }, "explain": [...] }, ... ] }

    Args:
        live_data: JSON response from /event/{gw}/live/.
        gameweek: Gameweek number for context.
        fixtures_df: Optional fixtures DataFrame to map fixture_id.

    Returns:
        DataFrame with columns matching fact_player_gameweeks schema.
    """
    elements = live_data.get("elements", [])
    if not elements:
        logger.warning("No live elements for GW%d.", gameweek)
        return pd.DataFrame()

    rows: list[dict] = []
    for elem in elements:
        player_id = elem.get("id")
        stats = elem.get("stats", {})

        # Determine fixture_id from explain block if available
        fixture_id = None
        explain = elem.get("explain", [])
        if explain and isinstance(explain, list):
            fixture_id = explain[0].get("fixture") if explain[0] else None

        row = {
            "player_id": player_id,
            "gameweek": gameweek,
            "fixture_id": fixture_id,
            "minutes": stats.get("minutes", 0),
            "goals_scored": stats.get("goals_scored", 0),
            "assists": stats.get("assists", 0),
            "clean_sheets": stats.get("clean_sheets", 0),
            "goals_conceded": stats.get("goals_conceded", 0),
            "own_goals": stats.get("own_goals", 0),
            "penalties_saved": stats.get("penalties_saved", 0),
            "penalties_missed": stats.get("penalties_missed", 0),
            "yellow_cards": stats.get("yellow_cards", 0),
            "red_cards": stats.get("red_cards", 0),
            "saves": stats.get("saves", 0),
            "bonus": stats.get("bonus", 0),
            "bps": stats.get("bps", 0),
            "influence": _safe_decimal(stats.get("influence", "0.0")),
            "creativity": _safe_decimal(stats.get("creativity", "0.0")),
            "threat": _safe_decimal(stats.get("threat", "0.0")),
            "ict_index": _safe_decimal(stats.get("ict_index", "0.0")),
            "starts": stats.get("starts", 0),
            "expected_goals": _safe_decimal(stats.get("expected_goals")),
            "expected_assists": _safe_decimal(stats.get("expected_assists")),
            "expected_goal_involvements": _safe_decimal(
                stats.get("expected_goal_involvements")
            ),
            "expected_goals_conceded": _safe_decimal(
                stats.get("expected_goals_conceded")
            ),
            "total_points": stats.get("total_points", 0),
        }
        rows.append(row)

    df = pd.DataFrame(rows)
    logger.info("Transformed %d player-gameweek rows for GW%d.", len(df), gameweek)
    return df


def aggregate_team_match_stats(
    player_gw_df: pd.DataFrame,
    players_df: pd.DataFrame,
    fixtures_df: pd.DataFrame,
    gameweek: int,
) -> pd.DataFrame:
    """Aggregate player-level stats into team-level match performances.

    Option A: Derive team stats by summing player stats per fixture per team.

    Args:
        player_gw_df: Player gameweek DataFrame (from transform_player_gameweek).
        players_df: Player dimension DataFrame (to map player→team).
        fixtures_df: Fixture dimension DataFrame (for scores, home/away).
        gameweek: Current gameweek number.

    Returns:
        DataFrame with columns matching fact_match_performances schema.
    """
    if player_gw_df.empty or players_df.empty:
        logger.warning("Cannot aggregate — empty input DataFrames.")
        return pd.DataFrame()

    # Merge player team info
    merged = player_gw_df.merge(
        players_df[["player_id", "team_id"]],
        on="player_id",
        how="left",
    )

    # Filter to players who actually played
    played = merged[merged["minutes"] > 0].copy()
    if played.empty:
        logger.warning("No players with minutes for GW%d.", gameweek)
        return pd.DataFrame()

    # Get fixtures for this gameweek
    gw_fixtures = fixtures_df[fixtures_df["gameweek"] == gameweek].copy()

    rows: list[dict] = []
    for _, fixture in gw_fixtures.iterrows():
        fixture_id = fixture["fixture_id"]
        team_h = fixture["team_h"]
        team_a = fixture["team_a"]

        for team_id, is_home in [(team_h, 1), (team_a, 0)]:
            opponent_id = team_a if is_home else team_h
            team_players = played[played["team_id"] == team_id]
            opp_players = played[played["team_id"] == opponent_id]

            goals = int(team_players["goals_scored"].sum())
            goals_conceded = int(opp_players["goals_scored"].sum())
            xg = float(team_players["expected_goals"].fillna(0).sum())
            xg_conceded = float(opp_players["expected_goals"].fillna(0).sum())

            # Derive approximate shots from threat metric
            # FPL threat: ~10 per shot attempt (rough heuristic)
            threat_total = float(team_players["threat"].sum())
            shots = max(int(threat_total / 10), goals)

            # Result
            if goals > goals_conceded:
                result = "W"
            elif goals < goals_conceded:
                result = "L"
            else:
                result = "D"

            rows.append({
                "fixture_id": fixture_id,
                "team_id": team_id,
                "gameweek": gameweek,
                "date_id": None,  # Resolved during load
                "is_home": is_home,
                "goals_scored": goals,
                "goals_conceded": goals_conceded,
                "shots": shots,
                "shots_on_target": max(goals, int(shots * 0.35)),
                "xg": round(xg, 2),
                "xg_conceded": round(xg_conceded, 2),
                "total_bps": int(team_players["bps"].sum()),
                "clean_sheet": 1 if goals_conceded == 0 else 0,
                "result": result,
            })

    df = pd.DataFrame(rows)
    logger.info(
        "Aggregated %d team match performances for GW%d.", len(df), gameweek
    )
    return df


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_decimal(value: any) -> Optional[float]:
    """Convert a value to float, returning None for non-numeric inputs.

    Args:
        value: Raw value from API (could be str, int, float, or None).

    Returns:
        Float value or None.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
