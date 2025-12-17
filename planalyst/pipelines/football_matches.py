"""
PLanalyst — dlt Pipeline: Football Match Data Ingestion (Bronze Layer)

Ingests Premier League match data from football-data.org API (v4)
into the bronze.raw_matches table in PostgreSQL.

Scope: 2026-2027 season ONLY (explicit season filter).
"""

import time
from datetime import datetime, timezone
from typing import Any, Generator

import dlt
import requests

from planalyst.config import (
    FOOTBALL_API_BASE_URL,
    FOOTBALL_DATA_API_KEY,
    PL_COMPETITION_CODE,
    PL_SEASON,
    POSTGRES_CONNECTION_STRING,
    SCHEMA_BRONZE,
)


# ── API Client ───────────────────────────────────────────────────────────────

class FootballDataClient:
    """Lightweight client for football-data.org v4 API with rate limiting."""

    BASE_URL = FOOTBALL_API_BASE_URL
    RATE_LIMIT_PAUSE = 6.5  # seconds between requests (free tier: 10 req/min)

    def __init__(self, api_key: str):
        self.session = requests.Session()
        self.session.headers.update({"X-Auth-Token": api_key})
        self._last_request_time = 0.0

    def _rate_limit(self) -> None:
        """Enforce rate limiting for free tier."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.RATE_LIMIT_PAUSE:
            time.sleep(self.RATE_LIMIT_PAUSE - elapsed)
        self._last_request_time = time.time()

    def get(self, endpoint: str, params: dict | None = None) -> dict:
        """Make a GET request with rate limiting and error handling."""
        self._rate_limit()
        url = f"{self.BASE_URL}/{endpoint}"
        response = self.session.get(url, params=params or {})

        if response.status_code == 429:
            # Rate limited — wait and retry once
            retry_after = int(response.headers.get("X-RequestCounter-Reset", 60))
            print(f"  ⏳ Rate limited. Waiting {retry_after}s...")
            time.sleep(retry_after)
            response = self.session.get(url, params=params or {})

        response.raise_for_status()
        return response.json()

    def get_matches(self, season: int, matchday: int | None = None) -> list[dict]:
        """Fetch matches for a specific season (and optionally matchday)."""
        params = {"season": season}
        if matchday is not None:
            params["matchday"] = matchday

        data = self.get(f"competitions/{PL_COMPETITION_CODE}/matches", params)
        return data.get("matches", [])


# ── dlt Resource ─────────────────────────────────────────────────────────────

@dlt.resource(
    name="raw_matches",
    write_disposition="merge",
    primary_key="id",
    columns={
        "id": {"data_type": "bigint"},
        "matchday": {"data_type": "bigint"},
        "home_team_id": {"data_type": "bigint"},
        "away_team_id": {"data_type": "bigint"},
        "score_home": {"data_type": "bigint", "nullable": True},
        "score_away": {"data_type": "bigint", "nullable": True},
        "score_home_ht": {"data_type": "bigint", "nullable": True},
        "score_away_ht": {"data_type": "bigint", "nullable": True},
        "season": {"data_type": "bigint"},
    },
)
def raw_matches_resource(
    api_key: str = FOOTBALL_DATA_API_KEY,
    season: int = PL_SEASON,
    matchday: int | None = None,
) -> Generator[dict[str, Any], None, None]:
    """
    dlt resource that yields flattened match records for the specified season.

    Each record is one match with home/away teams, scores, and metadata.
    Uses merge write disposition so re-running updates existing matches
    (e.g., when a SCHEDULED match becomes FINISHED).
    """
    client = FootballDataClient(api_key)

    print(f"📥 Fetching PL matches for season {season}-{season + 1}...")
    if matchday:
        print(f"   Filtering to matchday {matchday}")

    matches = client.get_matches(season=season, matchday=matchday)
    print(f"   Found {len(matches)} matches")

    for match in matches:
        # Flatten the nested API response into a clean record
        yield {
            "id": match["id"],
            "matchday": match["matchday"],
            "status": match["status"],
            "stage": match.get("stage", "REGULAR_SEASON"),
            "utc_date": match["utcDate"],
            # Home team
            "home_team_id": match["homeTeam"]["id"],
            "home_team_name": match["homeTeam"]["name"],
            "home_team_short": match["homeTeam"].get("shortName", ""),
            "home_team_tla": match["homeTeam"].get("tla", ""),
            "home_team_crest": match["homeTeam"].get("crest", ""),
            # Away team
            "away_team_id": match["awayTeam"]["id"],
            "away_team_name": match["awayTeam"]["name"],
            "away_team_short": match["awayTeam"].get("shortName", ""),
            "away_team_tla": match["awayTeam"].get("tla", ""),
            "away_team_crest": match["awayTeam"].get("crest", ""),
            # Scores (null if match not yet played)
            "score_winner": match["score"].get("winner"),
            "score_home": match["score"]["fullTime"].get("home"),
            "score_away": match["score"]["fullTime"].get("away"),
            "score_home_ht": match["score"]["halfTime"].get("home"),
            "score_away_ht": match["score"]["halfTime"].get("away"),
            # Metadata
            "season": season,
            "competition_code": PL_COMPETITION_CODE,
            "last_updated": match.get("lastUpdated"),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }


# ── dlt Pipeline ─────────────────────────────────────────────────────────────

def create_pipeline() -> dlt.Pipeline:
    """Create the football matches dlt pipeline targeting bronze schema."""
    return dlt.pipeline(
        pipeline_name="planalyst_football_matches",
        destination=dlt.destinations.postgres(credentials=POSTGRES_CONNECTION_STRING),
        dataset_name=SCHEMA_BRONZE,
    )


def run_pipeline(matchday: int | None = None) -> None:
    """Run the football matches ingestion pipeline."""
    pipeline = create_pipeline()
    resource = raw_matches_resource(matchday=matchday)

    print(f"\n🚀 Running football matches pipeline → {SCHEMA_BRONZE}.raw_matches")
    load_info = pipeline.run(resource)
    print(f"✅ Load complete!")
    print(f"   {load_info}")


# ── CLI Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ingest PL match data into bronze layer")
    parser.add_argument(
        "--matchday",
        type=int,
        default=None,
        help="Specific matchday to ingest (default: all available)",
    )
    args = parser.parse_args()

    if not FOOTBALL_DATA_API_KEY:
        raise ValueError("FOOTBALL_DATA_API_KEY not set in .env!")

    run_pipeline(matchday=args.matchday)
