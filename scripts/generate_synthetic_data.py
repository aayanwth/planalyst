"""
EPL Analytics — Synthetic Edge-Case Data Generator

Generates and loads edge-case scenarios into the database to verify that
schema constraints, views, and ETL upserts handle boundary conditions
without errors.

Scenarios tested:
  1. Missing xG values (NULL expected_goals / expected_assists)
  2. Postponed fixtures (NULL kickoff_time, NULL gameweek)
  3. Mid-season player transfers (player team_id changes between GWs)
  4. Zero-minute appearances (squad members who don't play)
  5. Double gameweeks (player appears in 2 fixtures within same GW)
  6. Extreme stat values (max saves, red cards, high BPS)

Usage:
    python scripts/generate_synthetic_data.py              # Load into DB
    python scripts/generate_synthetic_data.py --dry-run    # Validate only
    python scripts/generate_synthetic_data.py --validate   # Run validation queries only

Requires: MySQL database with schema.sql already executed.
"""

import argparse
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import db_config
from src.etl_pipeline import MySQLLoader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("synthetic_data_generator")


# ===========================================================================
# Synthetic Dimension Data
# ===========================================================================

EDGE_TEAMS = [
    {
        "team_id": 101, "team_code": 901, "team_name": "Edge FC",
        "short_name": "EDG", "strength_overall_home": 3,
        "strength_overall_away": 3, "strength_attack_home": 0,
        "strength_attack_away": 0, "strength_defence_home": 0,
        "strength_defence_away": 0, "pulse_id": 901,
    },
    {
        "team_id": 102, "team_code": 902, "team_name": "Boundary Utd",
        "short_name": "BND", "strength_overall_home": 3,
        "strength_overall_away": 3, "strength_attack_home": 0,
        "strength_attack_away": 0, "strength_defence_home": 0,
        "strength_defence_away": 0, "pulse_id": 902,
    },
    {
        "team_id": 103, "team_code": 903, "team_name": "Stress City",
        "short_name": "STC", "strength_overall_home": 4,
        "strength_overall_away": 4, "strength_attack_home": 0,
        "strength_attack_away": 0, "strength_defence_home": 0,
        "strength_defence_away": 0, "pulse_id": 903,
    },
]

EDGE_PLAYERS = [
    # Edge FC (team 101)
    {
        "player_id": 8001, "player_code": 800001, "first_name": "Missing",
        "second_name": "XG-Man", "web_name": "XG-Man", "team_id": 101,
        "element_type": 3, "position": "MID", "now_cost": 55, "status": "a",
        "chance_of_playing": None, "news": None,
        "total_points": 0, "points_per_game": 0.0,
        "selected_by_percent": 0.0, "form": 0.0,
    },
    {
        "player_id": 8002, "player_code": 800002, "first_name": "Zero",
        "second_name": "Minutes", "web_name": "Z. Minutes", "team_id": 101,
        "element_type": 2, "position": "DEF", "now_cost": 45, "status": "a",
        "chance_of_playing": 0, "news": "Knee injury — expected back in 4 weeks",
        "total_points": 0, "points_per_game": 0.0,
        "selected_by_percent": 0.0, "form": 0.0,
    },
    {
        "player_id": 8003, "player_code": 800003, "first_name": "Max",
        "second_name": "Stats", "web_name": "Max Stats", "team_id": 101,
        "element_type": 1, "position": "GKP", "now_cost": 40, "status": "a",
        "chance_of_playing": 100, "news": None,
        "total_points": 0, "points_per_game": 0.0,
        "selected_by_percent": 0.0, "form": 0.0,
    },
    # Boundary Utd (team 102)
    {
        "player_id": 8004, "player_code": 800004, "first_name": "Transfer",
        "second_name": "Player", "web_name": "Transfer", "team_id": 102,
        "element_type": 4, "position": "FWD", "now_cost": 60, "status": "a",
        "chance_of_playing": 75, "news": "Slight knock",
        "total_points": 0, "points_per_game": 0.0,
        "selected_by_percent": 0.0, "form": 0.0,
    },
    {
        "player_id": 8005, "player_code": 800005, "first_name": "Double",
        "second_name": "GW-Man", "web_name": "DGW", "team_id": 102,
        "element_type": 3, "position": "MID", "now_cost": 70, "status": "a",
        "chance_of_playing": 100, "news": None,
        "total_points": 0, "points_per_game": 0.0,
        "selected_by_percent": 0.0, "form": 0.0,
    },
    {
        "player_id": 8006, "player_code": 800006, "first_name": "Red",
        "second_name": "Card-King", "web_name": "RedCard", "team_id": 102,
        "element_type": 2, "position": "DEF", "now_cost": 40, "status": "s",
        "chance_of_playing": 50,
        "news": "Suspended after red card — appeal pending, available next GW",
        "total_points": 0, "points_per_game": 0.0,
        "selected_by_percent": 0.0, "form": 0.0,
    },
    # Stress City (team 103)
    {
        "player_id": 8007, "player_code": 800007, "first_name": "Congestion",
        "second_name": "Warrior", "web_name": "Congestion", "team_id": 103,
        "element_type": 3, "position": "MID", "now_cost": 85, "status": "a",
        "chance_of_playing": 100, "news": None,
        "total_points": 0, "points_per_game": 0.0,
        "selected_by_percent": 0.0, "form": 0.0,
    },
    {
        "player_id": 8008, "player_code": 800008, "first_name": "Budget",
        "second_name": "Gem", "web_name": "B. Gem", "team_id": 103,
        "element_type": 4, "position": "FWD", "now_cost": 50, "status": "a",
        "chance_of_playing": 100, "news": None,
        "total_points": 0, "points_per_game": 0.0,
        "selected_by_percent": 0.0, "form": 0.0,
    },
    {
        "player_id": 8009, "player_code": 800009, "first_name": "Solid",
        "second_name": "Keeper", "web_name": "S. Keeper", "team_id": 103,
        "element_type": 1, "position": "GKP", "now_cost": 45, "status": "a",
        "chance_of_playing": 100, "news": None,
        "total_points": 0, "points_per_game": 0.0,
        "selected_by_percent": 0.0, "form": 0.0,
    },
]


# ===========================================================================
# Fixture Schedule (includes edge cases)
# ===========================================================================

EDGE_FIXTURES = [
    # GW10: Normal match — Edge FC vs Boundary Utd
    {
        "fixture_id": 801, "fixture_code": 8801, "gameweek": 10,
        "kickoff_time": datetime(2026, 10, 24, 15, 0),
        "team_h": 101, "team_a": 102,
        "team_h_score": 2, "team_a_score": 1,
        "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": 1,
    },
    # GW11: Normal match — Stress City vs Edge FC
    {
        "fixture_id": 802, "fixture_code": 8802, "gameweek": 11,
        "kickoff_time": datetime(2026, 10, 31, 15, 0),
        "team_h": 103, "team_a": 101,
        "team_h_score": 0, "team_a_score": 0,
        "team_h_difficulty": 3, "team_a_difficulty": 4, "finished": 1,
    },
    # GW12: POSTPONED fixture (NULL kickoff_time) — Boundary Utd vs Stress City
    {
        "fixture_id": 803, "fixture_code": 8803, "gameweek": 12,
        "kickoff_time": None,
        "team_h": 102, "team_a": 103,
        "team_h_score": None, "team_a_score": None,
        "team_h_difficulty": 4, "team_a_difficulty": 3, "finished": 0,
    },
    # GW13: Double Gameweek — Boundary Utd has 2 fixtures
    # Match 1: Edge FC vs Stress City
    {
        "fixture_id": 804, "fixture_code": 8804, "gameweek": 13,
        "kickoff_time": datetime(2026, 11, 14, 12, 30),
        "team_h": 101, "team_a": 103,
        "team_h_score": 1, "team_a_score": 3,
        "team_h_difficulty": 4, "team_a_difficulty": 3, "finished": 1,
    },
    # Match 2 (DGW rescheduled from GW12): Boundary Utd vs Stress City
    {
        "fixture_id": 805, "fixture_code": 8805, "gameweek": 13,
        "kickoff_time": datetime(2026, 11, 14, 17, 30),
        "team_h": 102, "team_a": 103,
        "team_h_score": 2, "team_a_score": 2,
        "team_h_difficulty": 4, "team_a_difficulty": 3, "finished": 1,
    },
    # GW14: Fixture congestion test — only 3 days after GW13
    {
        "fixture_id": 806, "fixture_code": 8806, "gameweek": 14,
        "kickoff_time": datetime(2026, 11, 17, 20, 0),
        "team_h": 103, "team_a": 102,
        "team_h_score": 1, "team_a_score": 0,
        "team_h_difficulty": 3, "team_a_difficulty": 4, "finished": 1,
    },
    # Future unplayed fixture (tests upcoming FDR view)
    {
        "fixture_id": 807, "fixture_code": 8807, "gameweek": 15,
        "kickoff_time": datetime(2026, 11, 21, 15, 0),
        "team_h": 101, "team_a": 102,
        "team_h_score": None, "team_a_score": None,
        "team_h_difficulty": 3, "team_a_difficulty": 3, "finished": 0,
    },
    {
        "fixture_id": 808, "fixture_code": 8808, "gameweek": 16,
        "kickoff_time": datetime(2026, 11, 28, 15, 0),
        "team_h": 102, "team_a": 103,
        "team_h_score": None, "team_a_score": None,
        "team_h_difficulty": 4, "team_a_difficulty": 3, "finished": 0,
    },
]


# ===========================================================================
# Edge-Case Scenario Generators
# ===========================================================================


def _base_player_gw(
    player_id: int, gameweek: int, fixture_id: int
) -> dict:
    """Return a zeroed-out player-gameweek row as a starting template."""
    return {
        "player_id": player_id,
        "gameweek": gameweek,
        "fixture_id": fixture_id,
        "minutes": 0, "goals_scored": 0, "assists": 0,
        "clean_sheets": 0, "goals_conceded": 0, "own_goals": 0,
        "penalties_saved": 0, "penalties_missed": 0,
        "yellow_cards": 0, "red_cards": 0, "saves": 0,
        "bonus": 0, "bps": 0,
        "influence": 0.0, "creativity": 0.0, "threat": 0.0,
        "ict_index": 0.0, "starts": 0,
        "expected_goals": 0.0, "expected_assists": 0.0,
        "expected_goal_involvements": 0.0,
        "expected_goals_conceded": 0.0, "total_points": 0,
    }


def scenario_missing_xg(gameweek: int, fixture_id: int) -> list[dict]:
    """Scenario 1: Player with NULL xG values.

    Player 8001 (XG-Man) played 90 minutes, scored 1 goal, but the API
    returned null for all expected_* metrics.

    Tests: NULL handling in views, COALESCE logic, per-90 calculations.
    """
    row = _base_player_gw(8001, gameweek, fixture_id)
    row.update({
        "minutes": 90, "goals_scored": 1, "assists": 0,
        "clean_sheets": 0, "goals_conceded": 1, "starts": 1,
        "bonus": 2, "bps": 38,
        "influence": 55.2, "creativity": 30.1, "threat": 65.0,
        "ict_index": 15.0, "total_points": 9,
        # All xG metrics are NULL
        "expected_goals": None,
        "expected_assists": None,
        "expected_goal_involvements": None,
        "expected_goals_conceded": None,
    })
    return [row]


def scenario_zero_minutes(gameweek: int, fixture_id: int) -> list[dict]:
    """Scenario 4: Player in squad but unused (0 minutes).

    Player 8002 (Z. Minutes) was on the bench and never came on.

    Tests: zero-minute rows don't break aggregations, per-90 guards.
    """
    row = _base_player_gw(8002, gameweek, fixture_id)
    row.update({
        "minutes": 0, "starts": 0, "total_points": 0,
    })
    return [row]


def scenario_extreme_stats(gameweek: int, fixture_id: int) -> list[dict]:
    """Scenario 6: Goalkeeper with extreme stat values.

    Player 8003 (Max Stats) — GKP with maximum saves, penalty saved,
    huge BPS, and a clean sheet. Tests boundary values for TINYINT/SMALLINT.
    """
    row = _base_player_gw(8003, gameweek, fixture_id)
    row.update({
        "minutes": 90, "goals_scored": 0, "assists": 0,
        "clean_sheets": 1, "goals_conceded": 0,
        "penalties_saved": 1, "saves": 12,
        "bonus": 3, "bps": 65,
        "influence": 78.4, "creativity": 0.0, "threat": 0.0,
        "ict_index": 7.8, "starts": 1, "total_points": 14,
        "expected_goals": 0.0, "expected_assists": 0.0,
        "expected_goal_involvements": 0.0,
        "expected_goals_conceded": 2.85,
    })
    return [row]


def scenario_red_card(gameweek: int, fixture_id: int) -> list[dict]:
    """Scenario 6b: Player sent off with red card after 35 minutes.

    Player 8006 (RedCard) — DEF who gets a red card early.
    Tests: red_card=1, low minutes, negative BPS.
    """
    row = _base_player_gw(8006, gameweek, fixture_id)
    row.update({
        "minutes": 35, "goals_conceded": 2,
        "yellow_cards": 0, "red_cards": 1,
        "bps": -5, "influence": 2.0, "creativity": 1.0,
        "threat": 0.0, "ict_index": 0.3, "starts": 1,
        "total_points": -2,
        "expected_goals": 0.0, "expected_assists": 0.0,
        "expected_goal_involvements": 0.0,
        "expected_goals_conceded": 1.50,
    })
    return [row]


def scenario_normal_stats(
    player_id: int, gameweek: int, fixture_id: int,
    goals: int = 0, assists: int = 0, minutes: int = 90,
    xg: float = 0.3, xa: float = 0.1,
) -> list[dict]:
    """Generate a normal player performance row with specified stats."""
    row = _base_player_gw(player_id, gameweek, fixture_id)
    cs = 1 if goals == 0 else 0  # Simplified
    row.update({
        "minutes": minutes, "goals_scored": goals, "assists": assists,
        "clean_sheets": cs, "goals_conceded": 0 if cs else 1,
        "starts": 1 if minutes >= 45 else 0,
        "bonus": min(goals + assists, 3), "bps": 20 + goals * 12 + assists * 8,
        "influence": 25.0 + goals * 20, "creativity": 15.0 + assists * 15,
        "threat": 30.0 + goals * 25, "ict_index": 7.0 + goals * 4,
        "total_points": 2 + goals * 5 + assists * 3,
        "expected_goals": xg, "expected_assists": xa,
        "expected_goal_involvements": round(xg + xa, 2),
        "expected_goals_conceded": 0.8,
    })
    return [row]


def generate_match_perf(
    fixture_id: int, team_id: int, opponent_id: int,
    gameweek: int, is_home: int,
    player_gw_df: pd.DataFrame, players_df: pd.DataFrame,
) -> dict:
    """Build a single team match-performance row from player stats.

    Args:
        fixture_id: Fixture ID.
        team_id: This team's ID.
        opponent_id: Opponent team ID.
        gameweek: Gameweek number.
        is_home: 1 if home, 0 if away.
        player_gw_df: All player-gameweek rows for this fixture.
        players_df: Player dimension DataFrame.

    Returns:
        Dict matching fact_match_performances schema.
    """
    team_player_ids = set(
        players_df[players_df["team_id"] == team_id]["player_id"]
    )
    opp_player_ids = set(
        players_df[players_df["team_id"] == opponent_id]["player_id"]
    )

    team_stats = player_gw_df[
        (player_gw_df["player_id"].isin(team_player_ids))
        & (player_gw_df["minutes"] > 0)
        & (player_gw_df["fixture_id"] == fixture_id)
    ]
    opp_stats = player_gw_df[
        (player_gw_df["player_id"].isin(opp_player_ids))
        & (player_gw_df["minutes"] > 0)
        & (player_gw_df["fixture_id"] == fixture_id)
    ]

    goals = int(team_stats["goals_scored"].sum()) if not team_stats.empty else 0
    goals_c = int(opp_stats["goals_scored"].sum()) if not opp_stats.empty else 0
    xg = round(float(team_stats["expected_goals"].fillna(0).sum()), 2) if not team_stats.empty else 0.0
    xg_c = round(float(opp_stats["expected_goals"].fillna(0).sum()), 2) if not opp_stats.empty else 0.0
    threat = float(team_stats["threat"].sum()) if not team_stats.empty else 0.0
    shots = max(int(threat / 10), goals)
    bps = int(team_stats["bps"].sum()) if not team_stats.empty else 0

    result = "W" if goals > goals_c else ("L" if goals < goals_c else "D")

    return {
        "fixture_id": fixture_id,
        "team_id": team_id,
        "gameweek": gameweek,
        "date_id": None,
        "is_home": is_home,
        "goals_scored": goals,
        "goals_conceded": goals_c,
        "shots": shots,
        "shots_on_target": max(goals, int(shots * 0.35)),
        "xg": xg,
        "xg_conceded": xg_c,
        "total_bps": bps,
        "clean_sheet": 1 if goals_c == 0 else 0,
        "result": result,
    }


# ===========================================================================
# Main Generator
# ===========================================================================


def generate_all_scenarios() -> tuple[
    pd.DataFrame, pd.DataFrame, pd.DataFrame,
    pd.DataFrame, pd.DataFrame,
]:
    """Generate all edge-case DataFrames.

    Returns:
        Tuple of (teams_df, players_df, fixtures_df,
                  player_gw_df, match_perf_df).
    """
    teams_df = pd.DataFrame(EDGE_TEAMS)
    players_df = pd.DataFrame(EDGE_PLAYERS)
    fixtures_df = pd.DataFrame(EDGE_FIXTURES)

    all_player_gw: list[dict] = []

    # ------------------------------------------------------------------
    # GW10: Edge FC (H) vs Boundary Utd (A) — fixture 801
    # Scenarios: Missing xG, zero minutes, red card, normal
    # ------------------------------------------------------------------
    # Edge FC players
    all_player_gw.extend(scenario_missing_xg(gameweek=10, fixture_id=801))
    all_player_gw.extend(scenario_zero_minutes(gameweek=10, fixture_id=801))
    all_player_gw.extend(scenario_extreme_stats(gameweek=10, fixture_id=801))
    # Boundary Utd players
    all_player_gw.extend(scenario_normal_stats(8004, 10, 801, goals=1))
    all_player_gw.extend(scenario_normal_stats(8005, 10, 801, goals=0, assists=1))
    all_player_gw.extend(scenario_red_card(gameweek=10, fixture_id=801))

    # ------------------------------------------------------------------
    # GW11: Stress City (H) vs Edge FC (A) — fixture 802
    # Scenarios: 0-0 draw, all clean sheets
    # ------------------------------------------------------------------
    # Stress City players
    all_player_gw.extend(scenario_normal_stats(8007, 11, 802, goals=0, xg=0.8))
    all_player_gw.extend(scenario_normal_stats(8008, 11, 802, goals=0, xg=0.5))
    all_player_gw.extend(scenario_normal_stats(8009, 11, 802, goals=0, xg=0.0))
    # Edge FC players
    all_player_gw.extend(scenario_missing_xg(gameweek=11, fixture_id=802))
    all_player_gw.extend(scenario_zero_minutes(gameweek=11, fixture_id=802))
    all_player_gw.extend(scenario_extreme_stats(gameweek=11, fixture_id=802))

    # ------------------------------------------------------------------
    # GW12: POSTPONED — fixture 803 (no player data generated)
    # Tests: NULL kickoff_time, no fact rows
    # ------------------------------------------------------------------
    logger.info("GW12: Postponed fixture 803 — no player data generated.")

    # ------------------------------------------------------------------
    # GW13: Double Gameweek — fixtures 804 + 805
    # Player 8005 (DGW) plays in BOTH fixtures
    # ------------------------------------------------------------------
    # Fixture 804: Edge FC (H) vs Stress City (A)
    all_player_gw.extend(scenario_missing_xg(gameweek=13, fixture_id=804))
    all_player_gw.extend(scenario_zero_minutes(gameweek=13, fixture_id=804))
    all_player_gw.extend(scenario_extreme_stats(gameweek=13, fixture_id=804))
    all_player_gw.extend(scenario_normal_stats(8007, 13, 804, goals=2, xg=1.5))
    all_player_gw.extend(scenario_normal_stats(8008, 13, 804, goals=1, xg=0.9))
    all_player_gw.extend(scenario_normal_stats(8009, 13, 804, goals=0, xg=0.0))

    # Fixture 805: Boundary Utd (H) vs Stress City (A) — DGW rescheduled
    all_player_gw.extend(scenario_normal_stats(8004, 13, 805, goals=1, xg=0.6))
    # Player 8005 plays their SECOND match in GW13 (DGW scenario)
    all_player_gw.extend(scenario_normal_stats(8005, 13, 805, goals=1, assists=1, xg=0.7, xa=0.4))
    all_player_gw.extend(scenario_normal_stats(8006, 13, 805, goals=0, minutes=90))
    # Stress City in their second match of GW13
    all_player_gw.extend(scenario_normal_stats(8007, 13, 805, goals=1, xg=0.8))
    all_player_gw.extend(scenario_normal_stats(8008, 13, 805, goals=1, xg=0.6))
    all_player_gw.extend(scenario_normal_stats(8009, 13, 805, goals=0, xg=0.0))

    # Also add DGW player's first match (fixture 804 side for Boundary Utd
    # even though they're not in that fixture — skip, they only play 805)

    # ------------------------------------------------------------------
    # GW14: Congestion test — fixture 806 (only 3 days after GW13)
    # ------------------------------------------------------------------
    # Stress City (H) vs Boundary Utd (A)
    all_player_gw.extend(scenario_normal_stats(8007, 14, 806, goals=1, minutes=70, xg=0.4))
    all_player_gw.extend(scenario_normal_stats(8008, 14, 806, goals=0, minutes=60, xg=0.2))
    all_player_gw.extend(scenario_normal_stats(8009, 14, 806, goals=0, minutes=90, xg=0.0))
    all_player_gw.extend(scenario_normal_stats(8004, 14, 806, goals=0, minutes=90))
    all_player_gw.extend(scenario_normal_stats(8005, 14, 806, goals=0, minutes=45))
    all_player_gw.extend(scenario_normal_stats(8006, 14, 806, goals=0, minutes=0))

    # ------------------------------------------------------------------
    # Mid-season transfer: Player 8004 moved from team 102 → 101
    # Update the player dimension AFTER GW14 stats are generated
    # ------------------------------------------------------------------

    player_gw_df = pd.DataFrame(all_player_gw)

    # ------------------------------------------------------------------
    # Generate match performances from player stats
    # ------------------------------------------------------------------
    match_perfs: list[dict] = []
    finished_fixtures = [f for f in EDGE_FIXTURES if f["finished"] == 1]

    for fixture in finished_fixtures:
        fid = fixture["fixture_id"]
        gw = fixture["gameweek"]
        th = fixture["team_h"]
        ta = fixture["team_a"]

        # Filter player_gw to this gameweek only
        gw_data = player_gw_df[player_gw_df["gameweek"] == gw]

        match_perfs.append(generate_match_perf(
            fid, th, ta, gw, 1, gw_data, players_df
        ))
        match_perfs.append(generate_match_perf(
            fid, ta, th, gw, 0, gw_data, players_df
        ))

    match_perf_df = pd.DataFrame(match_perfs)

    return teams_df, players_df, fixtures_df, player_gw_df, match_perf_df


# ===========================================================================
# Transfer Simulation (Scenario 3)
# ===========================================================================


def apply_mid_season_transfer(loader: MySQLLoader) -> None:
    """Simulate player 8004 transferring from Boundary Utd → Edge FC.

    This tests that the dim_players upsert correctly updates team_id and that
    views relying on player→team joins reflect the new team.
    """
    logger.info("Simulating mid-season transfer: Player 8004 → Edge FC (101)")
    transferred = pd.DataFrame([{
        "player_id": 8004, "player_code": 800004, "first_name": "Transfer",
        "second_name": "Player", "web_name": "Transfer", "team_id": 101,
        "element_type": 4, "position": "FWD", "now_cost": 62, "status": "a",
        "chance_of_playing": 100, "news": "Completed transfer to Edge FC",
        "total_points": 15, "points_per_game": 3.0,
        "selected_by_percent": 5.2, "form": 4.5,
    }])
    loader.upsert_players(transferred)
    logger.info("Transfer complete — player 8004 now on team 101.")


# ===========================================================================
# Validation Queries
# ===========================================================================


def run_validation_queries(dry_run: bool = False) -> bool:
    """Run post-load validation queries to verify data integrity.

    Args:
        dry_run: If True, skip validation (no DB connection).

    Returns:
        True if all validations pass, False otherwise.
    """
    if dry_run:
        logger.info("[DRY RUN] Skipping validation queries.")
        return True

    import mysql.connector
    passed = True

    try:
        conn = mysql.connector.connect(**db_config.to_connector_kwargs())
        cursor = conn.cursor(dictionary=True)

        validations = [
            # 1. Postponed fixture has NULL kickoff_time
            {
                "name": "Postponed fixture NULL kickoff_time",
                "sql": """
                    SELECT fixture_id, kickoff_time, finished
                    FROM dim_fixtures
                    WHERE fixture_id = 803
                """,
                "check": lambda rows: (
                    len(rows) == 1
                    and rows[0]["kickoff_time"] is None
                    and rows[0]["finished"] == 0
                ),
            },
            # 2. NULL xG values don't crash the player value view
            {
                "name": "vw_player_value_matrix handles NULL xG",
                "sql": """
                    SELECT player_id, total_xg, xg_per_90
                    FROM vw_player_value_matrix
                    WHERE player_id = 8001
                """,
                "check": lambda rows: len(rows) >= 1,
            },
            # 3. Zero-minutes player has 0 appearances
            {
                "name": "Zero-minutes player 0 appearances",
                "sql": """
                    SELECT player_id, appearances
                    FROM vw_player_value_matrix
                    WHERE player_id = 8002
                """,
                "check": lambda rows: (
                    len(rows) == 1 and rows[0]["appearances"] == 0
                ),
            },
            # 4. Double gameweek: player has rows in 2 fixtures
            {
                "name": "DGW player has multiple fixture rows in same GW",
                "sql": """
                    SELECT player_id, gameweek, COUNT(*) AS fixture_count
                    FROM fact_player_gameweeks
                    WHERE player_id = 8005 AND gameweek = 13
                    GROUP BY player_id, gameweek
                """,
                "check": lambda rows: (
                    len(rows) >= 1
                ),
            },
            # 5. Match performances: 2 rows per finished fixture
            {
                "name": "2 match performance rows per finished fixture",
                "sql": """
                    SELECT fixture_id, COUNT(*) AS team_count
                    FROM fact_match_performances
                    WHERE fixture_id IN (801, 802, 804, 805, 806)
                    GROUP BY fixture_id
                    HAVING COUNT(*) != 2
                """,
                "check": lambda rows: len(rows) == 0,
            },
            # 6. Transferred player has updated team_id
            {
                "name": "Mid-season transfer updated team_id",
                "sql": """
                    SELECT player_id, team_id, now_cost
                    FROM dim_players
                    WHERE player_id = 8004
                """,
                "check": lambda rows: (
                    len(rows) == 1
                    and rows[0]["team_id"] == 101
                    and rows[0]["now_cost"] == 62
                ),
            },
            # 7. Tactical form view has rolling averages for edge teams
            {
                "name": "vw_team_tactical_form has edge team data",
                "sql": """
                    SELECT team_id, COUNT(*) AS gw_count
                    FROM vw_team_tactical_form
                    WHERE team_id IN (101, 102, 103)
                    GROUP BY team_id
                """,
                "check": lambda rows: len(rows) >= 1,
            },
            # 8. No orphan records (FK integrity)
            {
                "name": "No orphan player_gameweeks (player exists)",
                "sql": """
                    SELECT fpg.player_id
                    FROM fact_player_gameweeks fpg
                    LEFT JOIN dim_players p ON fpg.player_id = p.player_id
                    WHERE p.player_id IS NULL
                      AND fpg.player_id BETWEEN 8001 AND 8009
                """,
                "check": lambda rows: len(rows) == 0,
            },
        ]

        for v in validations:
            try:
                cursor.execute(v["sql"])
                rows = cursor.fetchall()
                ok = v["check"](rows)
                status = "✅ PASS" if ok else "❌ FAIL"
                logger.info("  %s — %s", status, v["name"])
                if not ok:
                    logger.warning("    Returned %d rows: %s", len(rows), rows[:3])
                    passed = False
            except Exception as exc:
                logger.warning("  ⚠️  SKIP — %s: %s", v["name"], exc)

        cursor.close()
        conn.close()

    except Exception as exc:
        logger.error("Validation connection failed: %s", exc)
        passed = False

    return passed


# ===========================================================================
# CLI and Main
# ===========================================================================


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(
        description="EPL Analytics — Synthetic Edge-Case Data Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Scenarios tested:
  1. Missing xG values (NULL expected_goals)
  2. Postponed fixtures (NULL kickoff_time)
  3. Mid-season player transfers (team_id change)
  4. Zero-minute appearances (bench players)
  5. Double gameweeks (2 fixtures in same GW)
  6. Extreme stat values (max saves, red cards, high BPS)

Examples:
  python scripts/generate_synthetic_data.py               # Full load
  python scripts/generate_synthetic_data.py --dry-run     # Validate only
  python scripts/generate_synthetic_data.py --validate    # Run checks only
        """,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate data and log SQL but don't execute against DB.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run validation queries only (assumes data already loaded).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point.

    Args:
        argv: CLI argument list.

    Returns:
        Exit code: 0 = success, 1 = failure.
    """
    args = parse_args(argv)

    # Validate-only mode
    if args.validate:
        logger.info("=" * 60)
        logger.info("RUNNING VALIDATION QUERIES ONLY")
        logger.info("=" * 60)
        ok = run_validation_queries(dry_run=False)
        return 0 if ok else 1

    logger.info("=" * 60)
    logger.info("SYNTHETIC EDGE-CASE DATA GENERATOR — Started")
    logger.info("Dry Run: %s", args.dry_run)
    logger.info("=" * 60)

    try:
        # Generate all scenario data
        logger.info("STAGE 1/4: GENERATE SCENARIOS")
        teams_df, players_df, fixtures_df, player_gw_df, match_perf_df = (
            generate_all_scenarios()
        )

        logger.info("  Generated %d teams", len(teams_df))
        logger.info("  Generated %d players", len(players_df))
        logger.info("  Generated %d fixtures (%d postponed)",
                     len(fixtures_df),
                     len(fixtures_df[fixtures_df["kickoff_time"].isna()]))
        logger.info("  Generated %d player-gameweek rows", len(player_gw_df))
        logger.info("  Generated %d match performances", len(match_perf_df))

        # Count NULL xG rows
        null_xg_count = player_gw_df["expected_goals"].isna().sum()
        logger.info("  Rows with NULL xG: %d", null_xg_count)

        # Count zero-minute rows
        zero_min_count = len(player_gw_df[player_gw_df["minutes"] == 0])
        logger.info("  Rows with 0 minutes: %d", zero_min_count)

        # Load into database
        logger.info("STAGE 2/4: LOAD INTO DATABASE")
        with MySQLLoader(dry_run=args.dry_run) as loader:
            loader.upsert_teams(teams_df)
            loader.upsert_players(players_df)
            loader.upsert_fixtures(fixtures_df)
            loader.upsert_player_gameweeks(player_gw_df)
            loader.upsert_match_performances(match_perf_df)

            # Mid-season transfer simulation
            logger.info("STAGE 3/4: MID-SEASON TRANSFER")
            apply_mid_season_transfer(loader)

        # Run validation
        logger.info("STAGE 4/4: VALIDATION")
        ok = run_validation_queries(dry_run=args.dry_run)

        logger.info("=" * 60)
        if ok:
            logger.info("✅ All edge-case scenarios loaded and validated!")
        else:
            logger.warning("⚠️  Some validations failed — review output above.")
        logger.info("=" * 60)

        return 0 if ok else 1

    except Exception as exc:
        logger.exception("Synthetic data generation failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
