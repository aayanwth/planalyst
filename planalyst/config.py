"""
PLanalyst — Shared configuration and constants.

Loads environment variables from .env and provides project-wide settings.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Load .env from project root ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models"
load_dotenv(PROJECT_ROOT / ".env")

# ── API Keys ─────────────────────────────────────────────────────────────────
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# ── PostgreSQL ───────────────────────────────────────────────────────────────
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "planalyst")
POSTGRES_USER = os.getenv("POSTGRES_USER", "planalyst")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "planalyst_dev")

POSTGRES_CONNECTION_STRING = (
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
    f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

# SQLAlchemy URL pinned to psycopg2 (newer SQLAlchemy defaults "postgresql://" to psycopg3)
SQLALCHEMY_CONNECTION_STRING = POSTGRES_CONNECTION_STRING.replace(
    "postgresql://", "postgresql+psycopg2://", 1
)

# ── MLflow ───────────────────────────────────────────────────────────────────
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")

# ── Season ───────────────────────────────────────────────────────────────────
PL_SEASON = int(os.getenv("PL_SEASON", "2026"))
PL_SEASON_LABEL = f"{PL_SEASON}-{PL_SEASON + 1}"
PL_SEASON_START_DATE = os.getenv("PL_SEASON_START_DATE", "2026-08-15")

# ── Football-data.org API ────────────────────────────────────────────────────
FOOTBALL_API_BASE_URL = "https://api.football-data.org/v4"
PL_COMPETITION_CODE = "PL"

# ── Premier League Teams (2026-27 — from football-data.org API) ──────────────
# These are the actual API names (with "FC" suffix) as returned by the v4 API.
PL_TEAMS_API = [
    "AFC Bournemouth",
    "Arsenal FC",
    "Aston Villa FC",
    "Brentford FC",
    "Brighton & Hove Albion FC",
    "Chelsea FC",
    "Coventry City FC",
    "Crystal Palace FC",
    "Everton FC",
    "Fulham FC",
    "Hull City AFC",
    "Ipswich Town FC",
    "Leeds United FC",
    "Liverpool FC",
    "Manchester City FC",
    "Manchester United FC",
    "Newcastle United FC",
    "Nottingham Forest FC",
    "Sunderland AFC",
    "Tottenham Hotspur FC",
]

# Short names for display / news search
PL_TEAMS_SHORT = [
    "Bournemouth",
    "Arsenal",
    "Aston Villa",
    "Brentford",
    "Brighton",
    "Chelsea",
    "Coventry City",
    "Crystal Palace",
    "Everton",
    "Fulham",
    "Hull City",
    "Ipswich Town",
    "Leeds United",
    "Liverpool",
    "Manchester City",
    "Manchester United",
    "Newcastle United",
    "Nottingham Forest",
    "Sunderland",
    "Tottenham",
]

# ── Schemas ──────────────────────────────────────────────────────────────────
SCHEMA_BRONZE = "bronze"
SCHEMA_SILVER = "silver"
SCHEMA_GOLD = "gold"
SCHEMA_TRAINING = "training"
# dbt prefixes custom schemas with the profile schema ("public")
DBT_SILVER_SCHEMA = "public_silver"
DBT_GOLD_SCHEMA = "public_gold"
