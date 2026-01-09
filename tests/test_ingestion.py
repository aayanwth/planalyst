"""
EPL Analytics — Ingestion Unit Tests

Tests the full Extract → Transform → Load pipeline components using
mocked API responses and database connections. No live dependencies required.

Run: pytest tests/test_ingestion.py -v
"""

import json
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest
import requests

from src.api_client import FPLClient, FPLAPIError
from src.transformers import (
    transform_teams,
    transform_players,
    transform_fixtures,
    transform_player_gameweek,
    aggregate_team_match_stats,
    _safe_decimal,
)
from src.etl_pipeline import parse_args, MySQLLoader


# ===========================================================================
# API Client Tests
# ===========================================================================

class TestFPLClient:
    """Tests for the FPL API client with mocked HTTP requests."""

    @patch("src.api_client.requests.Session")
    def test_get_bootstrap_static_success(self, mock_session_cls, bootstrap_data):
        """Client should parse bootstrap-static JSON successfully."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = bootstrap_data
        mock_response.status_code = 200
        mock_response.content = b"test"
        mock_response.raise_for_status.return_value = None
        mock_session.get.return_value = mock_response
        mock_session_cls.return_value = mock_session

        client = FPLClient()
        client._session = mock_session
        result = client.get_bootstrap_static()

        assert "teams" in result
        assert "elements" in result
        assert len(result["teams"]) == 3

    @patch("src.api_client.requests.Session")
    def test_api_client_retries_on_server_error(self, mock_session_cls):
        """Client should retry on 500/503 errors then succeed."""
        mock_session = MagicMock()

        # First 2 calls fail with 503, third succeeds
        fail_response = MagicMock()
        fail_response.status_code = 503
        fail_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            response=fail_response
        )

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = {"teams": []}
        success_response.content = b"ok"
        success_response.raise_for_status.return_value = None

        mock_session.get.side_effect = [
            fail_response, fail_response, success_response
        ]
        mock_session_cls.return_value = mock_session

        client = FPLClient()
        client._session = mock_session

        # Third call should succeed
        result = client._get("https://example.com/api/test")
        assert mock_session.get.call_count == 3
        assert result == {"teams": []}

    def test_event_live_invalid_gameweek(self):
        """Client should raise ValueError for out-of-range gameweek."""
        client = FPLClient()
        with pytest.raises(ValueError, match="Gameweek must be 1-38"):
            client.get_event_live(0)
        with pytest.raises(ValueError, match="Gameweek must be 1-38"):
            client.get_event_live(39)


# ===========================================================================
# Transformer Tests
# ===========================================================================

class TestTransformTeams:
    """Tests for team dimension transformer."""

    def test_transform_teams_shape(self, bootstrap_data):
        """Should return DataFrame with correct number of rows and columns."""
        df = transform_teams(bootstrap_data)
        assert len(df) == 3
        assert "team_id" in df.columns
        assert "team_name" in df.columns
        assert "short_name" in df.columns

    def test_transform_teams_values(self, bootstrap_data):
        """Should correctly map team IDs and names."""
        df = transform_teams(bootstrap_data)
        arsenal = df[df["team_id"] == 1].iloc[0]
        assert arsenal["team_name"] == "Arsenal"
        assert arsenal["short_name"] == "ARS"
        assert arsenal["strength_overall_home"] == 4

    def test_transform_teams_empty(self):
        """Should return empty DataFrame for missing teams key."""
        df = transform_teams({"teams": []})
        assert df.empty

        df = transform_teams({})
        assert df.empty


class TestTransformPlayers:
    """Tests for player dimension transformer."""

    def test_transform_players_shape(self, bootstrap_data):
        """Should return DataFrame with all 6 sample players."""
        df = transform_players(bootstrap_data)
        assert len(df) == 6

    def test_transform_players_cost_integrity(self, bootstrap_data):
        """now_cost should remain as raw integer (tenths of £M)."""
        df = transform_players(bootstrap_data)
        saka = df[df["player_id"] == 10].iloc[0]
        assert saka["now_cost"] == 105  # £10.5M stored as 105

    def test_transform_players_position_mapping(self, bootstrap_data):
        """Element type should map to correct position string."""
        df = transform_players(bootstrap_data)
        raya = df[df["player_id"] == 1].iloc[0]
        assert raya["position"] == "GKP"
        assert raya["element_type"] == 1

        saka = df[df["player_id"] == 10].iloc[0]
        assert saka["position"] == "MID"

        havertz = df[df["player_id"] == 400].iloc[0]
        assert havertz["position"] == "FWD"

    def test_transform_players_numeric_conversion(self, bootstrap_data):
        """String numeric fields should convert to float."""
        df = transform_players(bootstrap_data)
        saka = df[df["player_id"] == 10].iloc[0]
        assert isinstance(saka["points_per_game"], float)
        assert saka["points_per_game"] == 5.5


class TestTransformFixtures:
    """Tests for fixture dimension transformer."""

    def test_transform_fixtures_shape(self, fixtures_data):
        """Should return all 6 sample fixtures."""
        df = transform_fixtures(fixtures_data)
        assert len(df) == 6

    def test_transform_fixtures_gameweek_mapping(self, fixtures_data):
        """Fixtures should map to correct gameweeks."""
        df = transform_fixtures(fixtures_data)
        gw1 = df[df["gameweek"] == 1]
        assert len(gw1) == 2

    def test_transform_fixtures_postponed_handling(self, fixtures_data):
        """Fixtures with null kickoff_time should be preserved as NaT."""
        df = transform_fixtures(fixtures_data)
        postponed = df[df["fixture_id"] == 5]
        assert len(postponed) == 1
        assert pd.isna(postponed.iloc[0]["kickoff_time"])

    def test_transform_fixtures_fdr_fields(self, fixtures_data):
        """FDR difficulty ratings should be present."""
        df = transform_fixtures(fixtures_data)
        row = df[df["fixture_id"] == 1].iloc[0]
        assert row["team_h_difficulty"] == 4
        assert row["team_a_difficulty"] == 5


class TestTransformPlayerGameweek:
    """Tests for player gameweek fact transformer."""

    def test_transform_player_gameweek_shape(self, event_live_data):
        """Should return all 6 players from live data."""
        df = transform_player_gameweek(event_live_data, gameweek=1)
        assert len(df) == 6

    def test_transform_player_gameweek_stats(self, event_live_data):
        """Should correctly extract nested stats."""
        df = transform_player_gameweek(event_live_data, gameweek=1)
        saka = df[df["player_id"] == 10].iloc[0]
        assert saka["goals_scored"] == 1
        assert saka["assists"] == 1
        assert saka["minutes"] == 90
        assert saka["total_points"] == 15

    def test_missing_xg_handling(self, event_live_data):
        """NULL xG values should become None, not crash."""
        df = transform_player_gameweek(event_live_data, gameweek=1)
        # Player 300 (Salah) has null xG in fixture
        salah = df[df["player_id"] == 300].iloc[0]
        assert salah["expected_goals"] is None
        assert salah["expected_assists"] is None

    def test_zero_minutes_player(self, event_live_data):
        """Player with 0 minutes should still have a row."""
        df = transform_player_gameweek(event_live_data, gameweek=1)
        salah = df[df["player_id"] == 300].iloc[0]
        assert salah["minutes"] == 0
        assert salah["starts"] == 0

    def test_fixture_id_from_explain(self, event_live_data):
        """fixture_id should be extracted from explain block."""
        df = transform_player_gameweek(event_live_data, gameweek=1)
        raya = df[df["player_id"] == 1].iloc[0]
        assert raya["fixture_id"] == 1


class TestAggregateTeamMatchStats:
    """Tests for team-level aggregation (Option A)."""

    def test_aggregation_produces_two_rows_per_fixture(
        self, event_live_data, bootstrap_data, fixtures_data
    ):
        """Each fixture should produce 2 rows (home + away team)."""
        players_df = transform_players(bootstrap_data)
        fixtures_df = transform_fixtures(fixtures_data)
        player_gw_df = transform_player_gameweek(event_live_data, gameweek=1)

        result = aggregate_team_match_stats(
            player_gw_df, players_df, fixtures_df, gameweek=1
        )
        # Fixture 1 has team_h=1 (Arsenal) and team_a=6 (Chelsea)
        fixture_1 = result[result["fixture_id"] == 1]
        assert len(fixture_1) == 2
        assert set(fixture_1["is_home"]) == {0, 1}

    def test_aggregation_goals_consistency(
        self, event_live_data, bootstrap_data, fixtures_data
    ):
        """Home team goals_scored should equal away team goals_conceded."""
        players_df = transform_players(bootstrap_data)
        fixtures_df = transform_fixtures(fixtures_data)
        player_gw_df = transform_player_gameweek(event_live_data, gameweek=1)

        result = aggregate_team_match_stats(
            player_gw_df, players_df, fixtures_df, gameweek=1
        )
        fixture_1 = result[result["fixture_id"] == 1]
        home = fixture_1[fixture_1["is_home"] == 1].iloc[0]
        away = fixture_1[fixture_1["is_home"] == 0].iloc[0]

        assert home["goals_scored"] == away["goals_conceded"]
        assert away["goals_scored"] == home["goals_conceded"]


# ===========================================================================
# Safe Decimal Helper Tests
# ===========================================================================

class TestSafeDecimal:
    """Tests for the _safe_decimal helper."""

    def test_string_to_float(self):
        assert _safe_decimal("1.23") == 1.23

    def test_int_to_float(self):
        assert _safe_decimal(5) == 5.0

    def test_none_returns_none(self):
        assert _safe_decimal(None) is None

    def test_invalid_string_returns_none(self):
        assert _safe_decimal("not_a_number") is None

    def test_zero_string(self):
        assert _safe_decimal("0.00") == 0.0


# ===========================================================================
# CLI Argument Tests
# ===========================================================================

class TestCLIParsing:
    """Tests for CLI argument parsing."""

    def test_default_args(self):
        """No args should set all defaults."""
        args = parse_args([])
        assert args.gameweek is None
        assert args.full_refresh is False
        assert args.dry_run is False

    def test_gameweek_param(self):
        """--gameweek should accept valid values."""
        args = parse_args(["--gameweek", "3"])
        assert args.gameweek == 3

    def test_gameweek_short_param(self):
        """-g should work as shorthand."""
        args = parse_args(["-g", "15"])
        assert args.gameweek == 15

    def test_dry_run_flag(self):
        args = parse_args(["--dry-run"])
        assert args.dry_run is True

    def test_full_refresh_flag(self):
        args = parse_args(["--full-refresh"])
        assert args.full_refresh is True

    def test_combined_flags(self):
        args = parse_args(["-g", "5", "--dry-run", "--full-refresh"])
        assert args.gameweek == 5
        assert args.dry_run is True
        assert args.full_refresh is True


# ===========================================================================
# Upsert Idempotency Tests
# ===========================================================================

class TestUpsertIdempotency:
    """Tests that upsert operations generate correct SQL."""

    def test_upsert_teams_generates_on_duplicate_key(
        self, mock_loader, bootstrap_data
    ):
        """upsert_teams should call executemany with ON DUPLICATE KEY."""
        loader, cursor = mock_loader
        teams_df = transform_teams(bootstrap_data)
        loader.upsert_teams(teams_df)

        cursor.executemany.assert_called_once()
        sql_arg = cursor.executemany.call_args[0][0]
        assert "ON DUPLICATE KEY UPDATE" in sql_arg
        assert "dim_teams" in sql_arg

    def test_upsert_players_generates_on_duplicate_key(
        self, mock_loader, bootstrap_data
    ):
        """upsert_players should call executemany with ON DUPLICATE KEY."""
        loader, cursor = mock_loader
        players_df = transform_players(bootstrap_data)
        loader.upsert_players(players_df)

        cursor.executemany.assert_called_once()
        sql_arg = cursor.executemany.call_args[0][0]
        assert "ON DUPLICATE KEY UPDATE" in sql_arg
        assert "dim_players" in sql_arg

    def test_upsert_player_gameweeks_uses_composite_pk(
        self, mock_loader, event_live_data
    ):
        """Player GW upsert should reference player_id + gameweek."""
        loader, cursor = mock_loader
        df = transform_player_gameweek(event_live_data, gameweek=1)
        loader.upsert_player_gameweeks(df)

        cursor.executemany.assert_called_once()
        sql_arg = cursor.executemany.call_args[0][0]
        assert "ON DUPLICATE KEY UPDATE" in sql_arg
        assert "player_id" in sql_arg
        assert "gameweek" in sql_arg

    def test_double_upsert_no_error(self, mock_loader, bootstrap_data):
        """Running upsert twice should not raise errors (idempotent)."""
        loader, cursor = mock_loader
        teams_df = transform_teams(bootstrap_data)

        # Run twice
        loader.upsert_teams(teams_df)
        loader.upsert_teams(teams_df)

        assert cursor.executemany.call_count == 2

    def test_empty_dataframe_skips_upsert(self, mock_loader):
        """Empty DataFrame should return 0 without executing SQL."""
        loader, cursor = mock_loader
        result = loader.upsert_teams(pd.DataFrame())
        assert result == 0
        cursor.executemany.assert_not_called()
