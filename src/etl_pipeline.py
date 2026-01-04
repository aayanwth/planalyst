"""
EPL Analytics — ETL Pipeline

Production-grade batch ETL pipeline that:
  1. Extracts data from FPL REST APIs
  2. Transforms JSON into clean DataFrames
  3. Loads into MySQL Star Schema with idempotent upserts

Usage:
    python -m src.etl_pipeline                    # Full refresh (dimensions + latest)
    python -m src.etl_pipeline --gameweek 3       # Incremental: ingest GW3 only
    python -m src.etl_pipeline --full-refresh     # Force reload all dimensions
    python -m src.etl_pipeline --dry-run          # Validate without writing to DB
"""

import argparse
import logging
import sys
from datetime import datetime
from typing import Optional

import mysql.connector
from mysql.connector import Error as MySQLError
import pandas as pd

from src.config import db_config
from src.api_client import FPLClient, FPLAPIError
from src.transformers import (
    transform_teams,
    transform_players,
    transform_fixtures,
    transform_player_gameweek,
    aggregate_team_match_stats,
)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("etl_pipeline")


# ===========================================================================
# Database Loader
# ===========================================================================

class MySQLLoader:
    """Handles all database write operations with idempotent upserts.

    Uses mysql.connector with manual transaction management.
    """

    def __init__(self, config: Optional[object] = None, dry_run: bool = False) -> None:
        """Initialise the loader.

        Args:
            config: DatabaseConfig instance. Defaults to global db_config.
            dry_run: If True, log SQL but don't execute.
        """
        self._config = config or db_config
        self._dry_run = dry_run
        self._conn: Optional[mysql.connector.MySQLConnection] = None

    def connect(self) -> None:
        """Establish MySQL connection."""
        try:
            self._conn = mysql.connector.connect(
                **self._config.to_connector_kwargs()
            )
            logger.info(
                "Connected to MySQL: %s@%s:%s/%s",
                self._config.user,
                self._config.host,
                self._config.port,
                self._config.database,
            )
        except MySQLError as exc:
            logger.error("MySQL connection failed: %s", exc)
            raise

    def close(self) -> None:
        """Close MySQL connection."""
        if self._conn and self._conn.is_connected():
            self._conn.close()
            logger.info("MySQL connection closed.")

    def __enter__(self) -> "MySQLLoader":
        self.connect()
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Dimension loaders
    # ------------------------------------------------------------------

    def upsert_teams(self, df: pd.DataFrame) -> int:
        """Upsert team dimension data.

        Args:
            df: Teams DataFrame from transform_teams().

        Returns:
            Number of rows affected.
        """
        if df.empty:
            return 0

        sql = """
            INSERT INTO dim_teams (
                team_id, team_code, team_name, short_name,
                strength_overall_home, strength_overall_away,
                strength_attack_home, strength_attack_away,
                strength_defence_home, strength_defence_away,
                pulse_id
            ) VALUES (
                %(team_id)s, %(team_code)s, %(team_name)s, %(short_name)s,
                %(strength_overall_home)s, %(strength_overall_away)s,
                %(strength_attack_home)s, %(strength_attack_away)s,
                %(strength_defence_home)s, %(strength_defence_away)s,
                %(pulse_id)s
            )
            ON DUPLICATE KEY UPDATE
                team_code = VALUES(team_code),
                team_name = VALUES(team_name),
                short_name = VALUES(short_name),
                strength_overall_home = VALUES(strength_overall_home),
                strength_overall_away = VALUES(strength_overall_away),
                strength_attack_home = VALUES(strength_attack_home),
                strength_attack_away = VALUES(strength_attack_away),
                strength_defence_home = VALUES(strength_defence_home),
                strength_defence_away = VALUES(strength_defence_away),
                pulse_id = VALUES(pulse_id)
        """
        return self._execute_batch(sql, df, "dim_teams")

    def upsert_players(self, df: pd.DataFrame) -> int:
        """Upsert player dimension data.

        Args:
            df: Players DataFrame from transform_players().

        Returns:
            Number of rows affected.
        """
        if df.empty:
            return 0

        sql = """
            INSERT INTO dim_players (
                player_id, player_code, first_name, second_name, web_name,
                team_id, element_type, position, now_cost, status,
                chance_of_playing, news, total_points, points_per_game,
                selected_by_percent, form
            ) VALUES (
                %(player_id)s, %(player_code)s, %(first_name)s, %(second_name)s,
                %(web_name)s, %(team_id)s, %(element_type)s, %(position)s,
                %(now_cost)s, %(status)s, %(chance_of_playing)s, %(news)s,
                %(total_points)s, %(points_per_game)s, %(selected_by_percent)s,
                %(form)s
            )
            ON DUPLICATE KEY UPDATE
                player_code = VALUES(player_code),
                first_name = VALUES(first_name),
                second_name = VALUES(second_name),
                web_name = VALUES(web_name),
                team_id = VALUES(team_id),
                element_type = VALUES(element_type),
                position = VALUES(position),
                now_cost = VALUES(now_cost),
                status = VALUES(status),
                chance_of_playing = VALUES(chance_of_playing),
                news = VALUES(news),
                total_points = VALUES(total_points),
                points_per_game = VALUES(points_per_game),
                selected_by_percent = VALUES(selected_by_percent),
                form = VALUES(form)
        """
        return self._execute_batch(sql, df, "dim_players")

    def upsert_fixtures(self, df: pd.DataFrame) -> int:
        """Upsert fixture dimension data with date_id resolution.

        Args:
            df: Fixtures DataFrame from transform_fixtures().

        Returns:
            Number of rows affected.
        """
        if df.empty:
            return 0

        # Resolve date_id for each fixture from dim_dates
        df = df.copy()
        df["date_id"] = None
        if "kickoff_time" in df.columns:
            for idx, row in df.iterrows():
                if pd.notna(row["kickoff_time"]):
                    date_id = self._resolve_date_id(
                        row["kickoff_time"]
                    )
                    df.at[idx, "date_id"] = date_id

        sql = """
            INSERT INTO dim_fixtures (
                fixture_id, fixture_code, gameweek, kickoff_time,
                team_h, team_a, team_h_score, team_a_score,
                team_h_difficulty, team_a_difficulty, finished, date_id
            ) VALUES (
                %(fixture_id)s, %(fixture_code)s, %(gameweek)s,
                %(kickoff_time)s, %(team_h)s, %(team_a)s,
                %(team_h_score)s, %(team_a_score)s,
                %(team_h_difficulty)s, %(team_a_difficulty)s,
                %(finished)s, %(date_id)s
            )
            ON DUPLICATE KEY UPDATE
                fixture_code = VALUES(fixture_code),
                gameweek = VALUES(gameweek),
                kickoff_time = VALUES(kickoff_time),
                team_h_score = VALUES(team_h_score),
                team_a_score = VALUES(team_a_score),
                team_h_difficulty = VALUES(team_h_difficulty),
                team_a_difficulty = VALUES(team_a_difficulty),
                finished = VALUES(finished),
                date_id = VALUES(date_id)
        """
        return self._execute_batch(sql, df, "dim_fixtures")

    # ------------------------------------------------------------------
    # Fact loaders
    # ------------------------------------------------------------------

    def upsert_player_gameweeks(self, df: pd.DataFrame) -> int:
        """Upsert player gameweek fact data.

        Uses composite PK (player_id, gameweek) for idempotent upserts.

        Args:
            df: Player gameweek DataFrame from transform_player_gameweek().

        Returns:
            Number of rows affected.
        """
        if df.empty:
            return 0

        sql = """
            INSERT INTO fact_player_gameweeks (
                player_id, gameweek, fixture_id, minutes,
                goals_scored, assists, clean_sheets, goals_conceded,
                own_goals, penalties_saved, penalties_missed,
                yellow_cards, red_cards, saves, bonus, bps,
                influence, creativity, threat, ict_index, starts,
                expected_goals, expected_assists,
                expected_goal_involvements, expected_goals_conceded,
                total_points
            ) VALUES (
                %(player_id)s, %(gameweek)s, %(fixture_id)s, %(minutes)s,
                %(goals_scored)s, %(assists)s, %(clean_sheets)s,
                %(goals_conceded)s, %(own_goals)s, %(penalties_saved)s,
                %(penalties_missed)s, %(yellow_cards)s, %(red_cards)s,
                %(saves)s, %(bonus)s, %(bps)s, %(influence)s,
                %(creativity)s, %(threat)s, %(ict_index)s, %(starts)s,
                %(expected_goals)s, %(expected_assists)s,
                %(expected_goal_involvements)s, %(expected_goals_conceded)s,
                %(total_points)s
            )
            ON DUPLICATE KEY UPDATE
                fixture_id = VALUES(fixture_id),
                minutes = VALUES(minutes),
                goals_scored = VALUES(goals_scored),
                assists = VALUES(assists),
                clean_sheets = VALUES(clean_sheets),
                goals_conceded = VALUES(goals_conceded),
                own_goals = VALUES(own_goals),
                penalties_saved = VALUES(penalties_saved),
                penalties_missed = VALUES(penalties_missed),
                yellow_cards = VALUES(yellow_cards),
                red_cards = VALUES(red_cards),
                saves = VALUES(saves),
                bonus = VALUES(bonus),
                bps = VALUES(bps),
                influence = VALUES(influence),
                creativity = VALUES(creativity),
                threat = VALUES(threat),
                ict_index = VALUES(ict_index),
                starts = VALUES(starts),
                expected_goals = VALUES(expected_goals),
                expected_assists = VALUES(expected_assists),
                expected_goal_involvements = VALUES(expected_goal_involvements),
                expected_goals_conceded = VALUES(expected_goals_conceded),
                total_points = VALUES(total_points)
        """
        return self._execute_batch(sql, df, "fact_player_gameweeks")

    def upsert_match_performances(self, df: pd.DataFrame) -> int:
        """Upsert team match performance fact data.

        Uses UNIQUE(fixture_id, team_id) for idempotent upserts.

        Args:
            df: Match performances DataFrame from aggregate_team_match_stats().

        Returns:
            Number of rows affected.
        """
        if df.empty:
            return 0

        # Resolve date_id from fixture kickoff dates
        df = df.copy()
        for idx, row in df.iterrows():
            if row.get("date_id") is None:
                date_id = self._resolve_date_id_from_fixture(row["fixture_id"])
                df.at[idx, "date_id"] = date_id

        sql = """
            INSERT INTO fact_match_performances (
                fixture_id, team_id, gameweek, date_id, is_home,
                goals_scored, goals_conceded, shots, shots_on_target,
                xg, xg_conceded, total_bps, clean_sheet, result
            ) VALUES (
                %(fixture_id)s, %(team_id)s, %(gameweek)s, %(date_id)s,
                %(is_home)s, %(goals_scored)s, %(goals_conceded)s,
                %(shots)s, %(shots_on_target)s, %(xg)s, %(xg_conceded)s,
                %(total_bps)s, %(clean_sheet)s, %(result)s
            )
            ON DUPLICATE KEY UPDATE
                gameweek = VALUES(gameweek),
                date_id = VALUES(date_id),
                is_home = VALUES(is_home),
                goals_scored = VALUES(goals_scored),
                goals_conceded = VALUES(goals_conceded),
                shots = VALUES(shots),
                shots_on_target = VALUES(shots_on_target),
                xg = VALUES(xg),
                xg_conceded = VALUES(xg_conceded),
                total_bps = VALUES(total_bps),
                clean_sheet = VALUES(clean_sheet),
                result = VALUES(result)
        """
        return self._execute_batch(sql, df, "fact_match_performances")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute_batch(
        self, sql: str, df: pd.DataFrame, table_name: str
    ) -> int:
        """Execute batch upsert for a DataFrame.

        Args:
            sql: Parameterised SQL with %(col)s placeholders.
            df: DataFrame whose rows become parameter dicts.
            table_name: Table name for logging.

        Returns:
            Number of rows affected.
        """
        # Convert all NaNs and NaTs to None so mysql-connector can insert NULLs
        df = df.astype(object).where(pd.notna(df), None)
        records = df.to_dict("records")
        if self._dry_run:
            logger.info(
                "[DRY RUN] Would upsert %d rows into %s", len(records), table_name
            )
            return len(records)

        cursor = self._conn.cursor()
        try:
            cursor.executemany(sql, records)
            self._conn.commit()
            affected = cursor.rowcount
            logger.info(
                "Upserted %d rows into %s (%d affected).",
                len(records), table_name, affected,
            )
            return affected
        except MySQLError as exc:
            self._conn.rollback()
            logger.error("Failed to upsert into %s: %s", table_name, exc)
            raise
        finally:
            cursor.close()

    def _resolve_date_id(self, dt: datetime) -> Optional[int]:
        """Look up date_id from dim_dates for a given datetime.

        Args:
            dt: Datetime or date value.

        Returns:
            date_id integer or None if not found.
        """
        if self._dry_run or dt is None:
            return None
        cursor = self._conn.cursor()
        try:
            if isinstance(dt, pd.Timestamp):
                dt = dt.to_pydatetime()
            date_val = dt.date() if hasattr(dt, "date") else dt
            cursor.execute(
                "SELECT date_id FROM dim_dates WHERE full_date = %s",
                (date_val,),
            )
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            cursor.close()

    def _resolve_date_id_from_fixture(self, fixture_id: int) -> Optional[int]:
        """Look up date_id via a fixture's kickoff_time.

        Args:
            fixture_id: Fixture ID to resolve.

        Returns:
            date_id integer or None.
        """
        if self._dry_run:
            return None
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "SELECT date_id FROM dim_fixtures WHERE fixture_id = %s",
                (fixture_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            cursor.close()


# ===========================================================================
# Pipeline Orchestrator
# ===========================================================================

def run_pipeline(
    gameweek: Optional[int] = None,
    full_refresh: bool = False,
    dry_run: bool = False,
) -> int:
    """Execute the ETL pipeline.

    Args:
        gameweek: Specific gameweek to ingest (incremental). None = latest.
        full_refresh: Force reload all dimension tables.
        dry_run: Validate without writing to DB.

    Returns:
        Exit code: 0 = success, 1 = failure.
    """
    logger.info("=" * 60)
    logger.info("EPL Analytics ETL Pipeline — Started")
    logger.info(
        "Mode: %s | Gameweek: %s | Dry Run: %s",
        "full-refresh" if full_refresh else "incremental",
        gameweek or "auto",
        dry_run,
    )
    logger.info("=" * 60)

    try:
        # ------------------------------------------------------------------
        # EXTRACT
        # ------------------------------------------------------------------
        logger.info("STAGE 1/3: EXTRACT")
        with FPLClient() as client:
            bootstrap_data = client.get_bootstrap_static()
            fixtures_data = client.get_fixtures()

            # Determine current gameweek if not specified
            if gameweek is None:
                events = bootstrap_data.get("events", [])
                current = [e for e in events if e.get("is_current")]
                if current:
                    gameweek = current[0]["id"]
                else:
                    # Pre-season: use first upcoming gameweek
                    upcoming = [e for e in events if e.get("is_next")]
                    gameweek = upcoming[0]["id"] if upcoming else 1
                logger.info("Auto-detected gameweek: %d", gameweek)

            # Only fetch live data if season has started
            live_data = None
            try:
                live_data = client.get_event_live(gameweek)
            except FPLAPIError:
                logger.warning(
                    "Live data not available for GW%d (season may not have started).",
                    gameweek,
                )

        # ------------------------------------------------------------------
        # TRANSFORM
        # ------------------------------------------------------------------
        logger.info("STAGE 2/3: TRANSFORM")
        teams_df = transform_teams(bootstrap_data)
        players_df = transform_players(bootstrap_data)
        fixtures_df = transform_fixtures(fixtures_data)

        player_gw_df = pd.DataFrame()
        match_perf_df = pd.DataFrame()
        if live_data:
            player_gw_df = transform_player_gameweek(live_data, gameweek)
            if not player_gw_df.empty:
                match_perf_df = aggregate_team_match_stats(
                    player_gw_df, players_df, fixtures_df, gameweek
                )

        # ------------------------------------------------------------------
        # LOAD
        # ------------------------------------------------------------------
        logger.info("STAGE 3/3: LOAD")
        with MySQLLoader(dry_run=dry_run) as loader:
            # Always load dimensions (idempotent)
            loader.upsert_teams(teams_df)
            loader.upsert_players(players_df)
            loader.upsert_fixtures(fixtures_df)

            # Load facts if data available
            if not player_gw_df.empty:
                loader.upsert_player_gameweeks(player_gw_df)
            if not match_perf_df.empty:
                loader.upsert_match_performances(match_perf_df)

        logger.info("=" * 60)
        logger.info("ETL Pipeline — Completed Successfully")
        logger.info("=" * 60)
        return 0

    except FPLAPIError as exc:
        logger.error("API extraction failed: %s", exc)
        return 1
    except MySQLError as exc:
        logger.error("Database load failed: %s", exc)
        return 1
    except Exception as exc:
        logger.exception("Unexpected pipeline failure: %s", exc)
        return 1


# ===========================================================================
# CLI Entry Point
# ===========================================================================

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(
        description="EPL Analytics ETL Pipeline — Ingest FPL data into MySQL DW",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.etl_pipeline                   # Auto-detect gameweek
  python -m src.etl_pipeline --gameweek 3      # Ingest GW3 only
  python -m src.etl_pipeline --full-refresh    # Reload all dimensions
  python -m src.etl_pipeline --dry-run         # Validate without writing
        """,
    )
    parser.add_argument(
        "--gameweek", "-g",
        type=int,
        choices=range(1, 39),
        metavar="N",
        help="Specific gameweek to ingest (1-38). Default: auto-detect.",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Force reload all dimension tables.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate pipeline without writing to database.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """Main entry point.

    Args:
        argv: CLI argument list.

    Returns:
        Exit code.
    """
    args = parse_args(argv)
    return run_pipeline(
        gameweek=args.gameweek,
        full_refresh=args.full_refresh,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
