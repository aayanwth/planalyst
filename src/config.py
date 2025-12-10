"""
EPL Analytics — Configuration Module

Loads database credentials and API settings from environment variables.
Uses python-dotenv to read from .env file in project root.
"""

import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load .env from project root (two levels up from src/config.py)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=_ENV_PATH)


@dataclass(frozen=True)
class DatabaseConfig:
    """MySQL connection parameters."""
    host: str = os.getenv("DB_HOST", "127.0.0.1")
    port: int = int(os.getenv("DB_PORT", "3306"))
    user: str = os.getenv("DB_USER", "root")
    password: str = os.getenv("DB_PASSWORD", "")
    database: str = os.getenv("DB_NAME", "epl_analytics_db")

    def to_connector_kwargs(self) -> dict:
        """Return dict suitable for mysql.connector.connect()."""
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "charset": "utf8mb4",
            "collation": "utf8mb4_unicode_ci",
            "autocommit": False,
        }


@dataclass(frozen=True)
class APIConfig:
    """FPL API endpoints and request settings."""
    base_url: str = "https://fantasy.premierleague.com/api"
    bootstrap_endpoint: str = "/bootstrap-static/"
    fixtures_endpoint: str = "/fixtures/"
    event_live_endpoint: str = "/event/{gw}/live/"  # format with gameweek
    request_timeout: int = 30  # seconds
    max_retries: int = 3
    retry_backoff: float = 1.0  # seconds (exponential)

    def event_live_url(self, gameweek: int) -> str:
        """Build full URL for a specific gameweek live endpoint."""
        return f"{self.base_url}{self.event_live_endpoint.format(gw=gameweek)}"


# ---------------------------------------------------------------------------
# Singleton instances (import these directly)
# ---------------------------------------------------------------------------
db_config = DatabaseConfig()
api_config = APIConfig()
