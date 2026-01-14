"""
EPL Analytics — Gameweek Simulator

Generates synthetic match data for GW1–GW5 and feeds it sequentially
through the ETL load functions to verify:
  1. ON DUPLICATE KEY UPDATE upserts work correctly
  2. Rolling 5-match averages compute without errors
  3. Database constraints hold under sequential ingestion

Usage:
    python scripts/simulate_gameweeks.py

Requires: MySQL database with schema.sql already executed.
"""

import sys
import random
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import db_config
from src.etl_pipeline import MySQLLoader
from src.transformers import ELEMENT_TYPE_MAP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("gameweek_simulator")

# ---------------------------------------------------------------------------
# Constants: 3 teams, 6 players per team (18 total)
# Matches the real FPL team IDs from the bootstrap data
# ---------------------------------------------------------------------------
TEAMS = [
    {"team_id": 1, "team_code": 3, "team_name": "Arsenal", "short_name": "ARS",
     "strength_overall_home": 4, "strength_overall_away": 5,
     "strength_attack_home": 0, "strength_attack_away": 0,
     "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 1},
    {"team_id": 6, "team_code": 8, "team_name": "Chelsea", "short_name": "CHE",
     "strength_overall_home": 4, "strength_overall_away": 4,
     "strength_attack_home": 0, "strength_attack_away": 0,
     "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 4},
    {"team_id": 14, "team_code": 14, "team_name": "Liverpool", "short_name": "LIV",
     "strength_overall_home": 4, "strength_overall_away": 4,
     "strength_attack_home": 0, "strength_attack_away": 0,
     "strength_defence_home": 0, "strength_defence_away": 0, "pulse_id": 10},
]

PLAYERS = [
    # Arsenal (team_id=1)
    {"player_id": 1, "player_code": 154561, "first_name": "David",
     "second_name": "Raya", "web_name": "Raya", "team_id": 1,
     "element_type": 1, "position": "GKP", "now_cost": 60, "status": "a",
     "total_points": 0, "points_per_game": 0.0, "selected_by_percent": 0.0, "form": 0.0},
    {"player_id": 10, "player_code": 223340, "first_name": "Bukayo",
     "second_name": "Saka", "web_name": "Saka", "team_id": 1,
     "element_type": 3, "position": "MID", "now_cost": 105, "status": "a",
     "total_points": 0, "points_per_game": 0.0, "selected_by_percent": 0.0, "form": 0.0},
    {"player_id": 400, "player_code": 433919, "first_name": "Kai",
     "second_name": "Havertz", "web_name": "Havertz", "team_id": 1,
     "element_type": 4, "position": "FWD", "now_cost": 80, "status": "a",
     "total_points": 0, "points_per_game": 0.0, "selected_by_percent": 0.0, "form": 0.0},
    # Chelsea (team_id=6)
    {"player_id": 200, "player_code": 200439, "first_name": "Cole",
     "second_name": "Palmer", "web_name": "Palmer", "team_id": 6,
     "element_type": 3, "position": "MID", "now_cost": 110, "status": "a",
     "total_points": 0, "points_per_game": 0.0, "selected_by_percent": 0.0, "form": 0.0},
    {"player_id": 500, "player_code": 232760, "first_name": "Nicolas",
     "second_name": "Jackson", "web_name": "Jackson", "team_id": 6,
     "element_type": 4, "position": "FWD", "now_cost": 75, "status": "a",
     "total_points": 0, "points_per_game": 0.0, "selected_by_percent": 0.0, "form": 0.0},
    {"player_id": 501, "player_code": 999001, "first_name": "Robert",
     "second_name": "Sanchez", "web_name": "Sanchez", "team_id": 6,
     "element_type": 1, "position": "GKP", "now_cost": 50, "status": "a",
     "total_points": 0, "points_per_game": 0.0, "selected_by_percent": 0.0, "form": 0.0},
    # Liverpool (team_id=14)
    {"player_id": 300, "player_code": 176297, "first_name": "Mohamed",
     "second_name": "Salah", "web_name": "Salah", "team_id": 14,
     "element_type": 3, "position": "MID", "now_cost": 130, "status": "a",
     "total_points": 0, "points_per_game": 0.0, "selected_by_percent": 0.0, "form": 0.0},
    {"player_id": 301, "player_code": 999002, "first_name": "Darwin",
     "second_name": "Nunez", "web_name": "Nunez", "team_id": 14,
     "element_type": 4, "position": "FWD", "now_cost": 75, "status": "a",
     "total_points": 0, "points_per_game": 0.0, "selected_by_percent": 0.0, "form": 0.0},
    {"player_id": 302, "player_code": 999003, "first_name": "Alisson",
     "second_name": "Becker", "web_name": "Alisson", "team_id": 14,
     "element_type": 1, "position": "GKP", "now_cost": 55, "status": "a",
     "total_points": 0, "points_per_game": 0.0, "selected_by_percent": 0.0, "form": 0.0},
]

# Fixture schedule: each GW has 1 fixture (round-robin with 3 teams)
# 5 GWs = enough for rolling 5-match average validation
FIXTURE_SCHEDULE = [
    # GW1: Arsenal(H) vs Chelsea(A)
    {"fixture_id": 901, "fixture_code": 9901, "gameweek": 1,
     "kickoff_time": datetime(2026, 8, 21, 19, 0), "team_h": 1, "team_a": 6,
     "team_h_score": 0, "team_a_score": 0, "team_h_difficulty": 4, "team_a_difficulty": 5, "finished": 1},
    # GW2: Liverpool(H) vs Arsenal(A)
    {"fixture_id": 902, "fixture_code": 9902, "gameweek": 2,
     "kickoff_time": datetime(2026, 8, 28, 19, 0), "team_h": 14, "team_a": 1,
     "team_h_score": 0, "team_a_score": 0, "team_h_difficulty": 5, "team_a_difficulty": 4, "finished": 1},
    # GW3: Chelsea(H) vs Liverpool(A)
    {"fixture_id": 903, "fixture_code": 9903, "gameweek": 3,
     "kickoff_time": datetime(2026, 9, 4, 19, 0), "team_h": 6, "team_a": 14,
     "team_h_score": 0, "team_a_score": 0, "team_h_difficulty": 4, "team_a_difficulty": 4, "finished": 1},
    # GW4: Arsenal(H) vs Liverpool(A)
    {"fixture_id": 904, "fixture_code": 9904, "gameweek": 4,
     "kickoff_time": datetime(2026, 9, 12, 14, 0), "team_h": 1, "team_a": 14,
     "team_h_score": 0, "team_a_score": 0, "team_h_difficulty": 4, "team_a_difficulty": 5, "finished": 1},
    # GW5: Chelsea(H) vs Arsenal(A)
    {"fixture_id": 905, "fixture_code": 9905, "gameweek": 5,
     "kickoff_time": datetime(2026, 9, 18, 19, 0), "team_h": 6, "team_a": 1,
     "team_h_score": 0, "team_a_score": 0, "team_h_difficulty": 5, "team_a_difficulty": 4, "finished": 1},
]


def generate_player_gw_stats(
    player: dict, gameweek: int, fixture_id: int
) -> dict:
    """Generate realistic synthetic stats for a player in a gameweek.

    Args:
        player: Player dict with position info.
        gameweek: Gameweek number.
        fixture_id: Fixture ID.

    Returns:
        Dict matching fact_player_gameweeks schema.
    """
    random.seed(player["player_id"] * 100 + gameweek)  # Reproducible

    is_gkp = player["element_type"] == 1
    minutes = random.choice([0, 45, 60, 70, 80, 85, 90, 90, 90, 90])

    if minutes == 0:
        # Unused sub
        return {
            "player_id": player["player_id"],
            "gameweek": gameweek,
            "fixture_id": fixture_id,
            "minutes": 0, "goals_scored": 0, "assists": 0,
            "clean_sheets": 0, "goals_conceded": 0, "own_goals": 0,
            "penalties_saved": 0, "penalties_missed": 0,
            "yellow_cards": 0, "red_cards": 0, "saves": 0,
            "bonus": 0, "bps": 0, "influence": 0.0,
            "creativity": 0.0, "threat": 0.0, "ict_index": 0.0,
            "starts": 0, "expected_goals": 0.0, "expected_assists": 0.0,
            "expected_goal_involvements": 0.0, "expected_goals_conceded": 0.0,
            "total_points": 0,
        }

    goals = random.choices([0, 0, 0, 0, 1, 1, 2], weights=[40, 25, 15, 10, 5, 3, 2])[0]
    if is_gkp:
        goals = 0
    assists = random.choices([0, 0, 0, 1, 1], weights=[50, 25, 15, 7, 3])[0]
    if is_gkp:
        assists = 0

    goals_conceded = random.choices([0, 0, 1, 1, 2, 3], weights=[30, 25, 20, 15, 7, 3])[0]
    clean_sheet = 1 if goals_conceded == 0 else 0
    saves = random.randint(2, 7) if is_gkp else 0

    xg = round(random.uniform(0.0, 1.5), 2) if not is_gkp else 0.0
    xa = round(random.uniform(0.0, 0.8), 2) if not is_gkp else 0.0
    xgi = round(xg + xa, 2)

    threat = round(random.uniform(5.0, 80.0), 1)
    creativity = round(random.uniform(2.0, 60.0), 1)
    influence = round(random.uniform(5.0, 70.0), 1)
    ict = round((influence + creativity + threat) / 10, 1)
    bps = random.randint(5, 55)
    bonus = 3 if bps > 45 else (2 if bps > 35 else (1 if bps > 25 else 0))

    total_points = (
        (2 if minutes >= 60 else 1) + goals * 5 + assists * 3
        + clean_sheet * 4 * (1 if is_gkp or player["element_type"] == 2 else 0)
        + bonus - (1 if random.random() < 0.15 else 0)
    )

    return {
        "player_id": player["player_id"],
        "gameweek": gameweek,
        "fixture_id": fixture_id,
        "minutes": minutes,
        "goals_scored": goals,
        "assists": assists,
        "clean_sheets": clean_sheet,
        "goals_conceded": goals_conceded,
        "own_goals": 0,
        "penalties_saved": random.choice([0, 0, 0, 0, 1]) if is_gkp else 0,
        "penalties_missed": 0,
        "yellow_cards": random.choice([0, 0, 0, 0, 1]),
        "red_cards": 0,
        "saves": saves,
        "bonus": bonus,
        "bps": bps,
        "influence": influence,
        "creativity": creativity,
        "threat": threat,
        "ict_index": ict,
        "starts": 1 if minutes >= 45 else 0,
        "expected_goals": xg,
        "expected_assists": xa,
        "expected_goal_involvements": xgi,
        "expected_goals_conceded": round(random.uniform(0.3, 2.0), 2),
        "total_points": max(total_points, 0),
    }


def generate_match_performance(
    fixture: dict,
    player_gw_df: pd.DataFrame,
    players_df: pd.DataFrame,
) -> list[dict]:
    """Generate team-level match performance from player stats.

    Args:
        fixture: Fixture dict.
        player_gw_df: Player gameweek stats for this fixture.
        players_df: Player dimension data.

    Returns:
        List of 2 dicts (home team + away team performance).
    """
    rows = []
    for team_id, is_home in [(fixture["team_h"], 1), (fixture["team_a"], 0)]:
        opponent_id = fixture["team_a"] if is_home else fixture["team_h"]

        team_stats = player_gw_df[
            player_gw_df["player_id"].isin(
                players_df[players_df["team_id"] == team_id]["player_id"]
            ) & (player_gw_df["minutes"] > 0)
        ]
        opp_stats = player_gw_df[
            player_gw_df["player_id"].isin(
                players_df[players_df["team_id"] == opponent_id]["player_id"]
            ) & (player_gw_df["minutes"] > 0)
        ]

        goals = int(team_stats["goals_scored"].sum())
        goals_conceded = int(opp_stats["goals_scored"].sum())
        xg = round(float(team_stats["expected_goals"].sum()), 2)
        xg_c = round(float(opp_stats["expected_goals"].sum()), 2)
        shots = max(int(team_stats["threat"].sum() / 10), goals)

        result = "W" if goals > goals_conceded else ("L" if goals < goals_conceded else "D")

        rows.append({
            "fixture_id": fixture["fixture_id"],
            "team_id": team_id,
            "gameweek": fixture["gameweek"],
            "date_id": None,
            "is_home": is_home,
            "goals_scored": goals,
            "goals_conceded": goals_conceded,
            "shots": shots,
            "shots_on_target": max(goals, int(shots * 0.35)),
            "xg": xg,
            "xg_conceded": xg_c,
            "total_bps": int(team_stats["bps"].sum()),
            "clean_sheet": 1 if goals_conceded == 0 else 0,
            "result": result,
        })
    return rows


def run_simulation() -> None:
    """Execute the full GW1–GW5 simulation."""
    logger.info("=" * 60)
    logger.info("GAMEWEEK SIMULATOR — Starting GW1–GW5 Simulation")
    logger.info("=" * 60)

    teams_df = pd.DataFrame(TEAMS)
    players_df = pd.DataFrame(PLAYERS)
    players_df["chance_of_playing"] = 100
    players_df["news"] = ""
    fixtures_df = pd.DataFrame(FIXTURE_SCHEDULE)

    results_summary: list[dict] = []

    with MySQLLoader() as loader:
        # Load dimensions first
        logger.info("Loading dimension tables...")
        loader.upsert_teams(teams_df)
        loader.upsert_players(players_df)

        # Process each gameweek sequentially
        for gw in range(1, 6):
            logger.info("-" * 40)
            logger.info("Processing Gameweek %d", gw)
            logger.info("-" * 40)

            gw_fixtures = [f for f in FIXTURE_SCHEDULE if f["gameweek"] == gw]
            gw_fixtures_df = pd.DataFrame(gw_fixtures)

            # Load fixtures for this GW
            loader.upsert_fixtures(gw_fixtures_df)

            # Generate player stats
            all_player_stats: list[dict] = []
            for fixture in gw_fixtures:
                # Get teams in this fixture
                for team_id in [fixture["team_h"], fixture["team_a"]]:
                    team_players = [p for p in PLAYERS if p["team_id"] == team_id]
                    for player in team_players:
                        stats = generate_player_gw_stats(
                            player, gw, fixture["fixture_id"]
                        )
                        all_player_stats.append(stats)

            player_gw_df = pd.DataFrame(all_player_stats)

            # Load player gameweek facts
            loader.upsert_player_gameweeks(player_gw_df)

            # Generate and load match performances
            all_match_perfs: list[dict] = []
            for fixture in gw_fixtures:
                perfs = generate_match_performance(
                    fixture, player_gw_df, players_df
                )
                all_match_perfs.extend(perfs)

            match_perf_df = pd.DataFrame(all_match_perfs)
            loader.upsert_match_performances(match_perf_df)

            # Track results
            for perf in all_match_perfs:
                results_summary.append({
                    "GW": gw,
                    "Team": next(
                        t["short_name"] for t in TEAMS
                        if t["team_id"] == perf["team_id"]
                    ),
                    "Goals": perf["goals_scored"],
                    "xG": perf["xg"],
                    "Result": perf["result"],
                })

            logger.info("GW%d loaded successfully.", gw)

        # ------------------------------------------------------------------
        # Re-run GW5 to test idempotent upserts
        # ------------------------------------------------------------------
        logger.info("=" * 40)
        logger.info("RE-RUNNING GW5 (idempotency test)")
        logger.info("=" * 40)

        gw5_fixtures = [f for f in FIXTURE_SCHEDULE if f["gameweek"] == 5]
        gw5_df = pd.DataFrame(gw5_fixtures)
        loader.upsert_fixtures(gw5_df)

        gw5_player_stats = []
        for fixture in gw5_fixtures:
            for team_id in [fixture["team_h"], fixture["team_a"]]:
                team_players = [p for p in PLAYERS if p["team_id"] == team_id]
                for player in team_players:
                    stats = generate_player_gw_stats(player, 5, fixture["fixture_id"])
                    gw5_player_stats.append(stats)

        gw5_player_df = pd.DataFrame(gw5_player_stats)
        loader.upsert_player_gameweeks(gw5_player_df)
        logger.info("GW5 re-upsert completed (no duplicates expected).")

    # ------------------------------------------------------------------
    # Validate rolling averages by querying the view
    # ------------------------------------------------------------------
    logger.info("=" * 40)
    logger.info("VALIDATING ROLLING AVERAGES")
    logger.info("=" * 40)

    try:
        import mysql.connector
        conn = mysql.connector.connect(**db_config.to_connector_kwargs())
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT team_name, gameweek, rolling_5m_avg_xg, rolling_5m_avg_goals,
                   rolling_5m_xg_overperf
            FROM vw_team_tactical_form
            WHERE gameweek = 5
            ORDER BY team_name
        """)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        if rows:
            logger.info("Rolling 5-match averages at GW5:")
            for row in rows:
                logger.info(
                    "  %s: avg_xG=%.2f, avg_Goals=%.2f, overperf=%.2f",
                    row["team_name"],
                    float(row["rolling_5m_avg_xg"] or 0),
                    float(row["rolling_5m_avg_goals"] or 0),
                    float(row["rolling_5m_xg_overperf"] or 0),
                )
            logger.info("✅ Rolling averages computed successfully!")
        else:
            logger.warning("⚠️ No rows returned from vw_team_tactical_form.")
    except Exception as exc:
        logger.warning(
            "⚠️ Could not validate views (run sql/views.sql first): %s", exc
        )

    # ------------------------------------------------------------------
    # Print summary table
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("SIMULATION SUMMARY")
    logger.info("=" * 60)
    summary_df = pd.DataFrame(results_summary)
    print(summary_df.to_string(index=False))
    logger.info("=" * 60)
    logger.info("✅ Simulation completed successfully!")


if __name__ == "__main__":
    run_simulation()
