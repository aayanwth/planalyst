"""
EPL Analytics — Shared Pytest Fixtures

Provides reusable test fixtures for API payloads and mock database connections.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# JSON payload fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bootstrap_data() -> dict:
    """Load sample bootstrap-static JSON payload."""
    with open(FIXTURES_DIR / "bootstrap_static.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def fixtures_data() -> list[dict]:
    """Load sample fixtures JSON payload."""
    with open(FIXTURES_DIR / "fixtures.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def event_live_data() -> dict:
    """Load sample event live JSON payload."""
    with open(FIXTURES_DIR / "event_live.json", "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Mock database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_mysql_connection():
    """Create a mock MySQL connection with cursor support."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    conn.is_connected.return_value = True
    cursor.rowcount = 0
    cursor.fetchone.return_value = (1,)  # Default: date_id = 1
    return conn, cursor


@pytest.fixture
def mock_loader(mock_mysql_connection):
    """Create a MySQLLoader with mocked connection (no real DB needed)."""
    from src.etl_pipeline import MySQLLoader
    conn, cursor = mock_mysql_connection
    loader = MySQLLoader(dry_run=False)
    loader._conn = conn
    return loader, cursor
