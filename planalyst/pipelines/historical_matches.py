"""
PLanalyst — dlt Pipeline: Historical Match Data (Training Dataset)

Ingests historical Premier League seasons from football-data.org into
a SEPARATE training schema. This data is ONLY used for model training
and must NEVER mix into the live bronze/silver/gold pipeline.

Scope: Multiple past seasons (as far back as the API supports).
"""

import time
from datetime import datetime, timezone
from typing import Any, Generator

import dlt

from planalyst.config import (
    POSTGRES_CONNECTION_STRING,
    FOOTBALL_API_BASE_URL,
    FOOTBALL_DATA_API_KEY,
    PL_COMPETITION_CODE,
    PL_SEASON,
    SCHEMA_TRAINING,
)
from planalyst.pipelines.football_matches import FootballDataClient


# Historical seasons to ingest (2015-16 through 2025-26)
# football-data.org free tier typically supports ~10 seasons back
HISTORICAL_SEASONS = list(range(2015, PL_SEASON))  # 2015 to 2025


@dlt.resource(
    name="historical_matches",
    write_disposition="merge",
    primary_key=["id"],
    columns={
        "id": {"data_type": "bigint"},
        "matchday": {"data_type": "bigint"},
        "home_team_id": {"data_type": "bigint"},
        "away_team_id": {"data_type": "bigint"},
        "score_home": {"data_type": "bigint", "nullable": True},
        "score_away": {"data_type": "bigint", "nullable": True},
        "season": {"data_type": "bigint"},
    },
)
def historical_matches_resource(
    api_key: str = FOOTBALL_DATA_API_KEY,
    seasons: list[int] | None = None,
) -> Generator[dict[str, Any], None, None]:
    """
    dlt resource yielding historical match data for training.
    Iterates over multiple past seasons.
    """
    if seasons is None:
        seasons = HISTORICAL_SEASONS

    client = FootballDataClient(api_key)

    for season in seasons:
        season_label = f"{season}-{season + 1}"
        print(f"  Fetching season {season_label}...")

        try:
            matches = client.get_matches(season=season)
            finished = [m for m in matches if m.get("status") == "FINISHED"]
            print(f"    Found {len(finished)} finished matches")

            for match in finished:
                yield {
                    "id": match["id"],
                    "matchday": match["matchday"],
                    "status": match["status"],
                    "utc_date": match["utcDate"],
                    "home_team_id": match["homeTeam"]["id"],
                    "home_team_name": match["homeTeam"]["name"],
                    "home_team_short": match["homeTeam"].get("shortName", ""),
                    "away_team_id": match["awayTeam"]["id"],
                    "away_team_name": match["awayTeam"]["name"],
                    "away_team_short": match["awayTeam"].get("shortName", ""),
                    "score_home": match["score"]["fullTime"].get("home"),
                    "score_away": match["score"]["fullTime"].get("away"),
                    "score_winner": match["score"].get("winner"),
                    "season": season,
                    "season_label": season_label,
                    "ingested_at": datetime.now(timezone.utc).isoformat(),
                }

        except Exception as e:
            print(f"    Warning: Failed to fetch season {season_label}: {e}")
            continue


def create_pipeline() -> dlt.Pipeline:
    """Create the historical matches dlt pipeline targeting training schema."""
    return dlt.pipeline(
        pipeline_name="planalyst_historical_matches",
        destination=dlt.destinations.postgres(credentials=POSTGRES_CONNECTION_STRING),
        dataset_name=SCHEMA_TRAINING,
    )


def run_pipeline(seasons: list[int] | None = None) -> None:
    """Run the historical matches ingestion pipeline."""
    pipeline = create_pipeline()
    resource = historical_matches_resource(seasons=seasons)

    print(f"\nRunning historical matches pipeline -> {SCHEMA_TRAINING}.historical_matches")
    load_info = pipeline.run(resource)
    print(f"Load complete!")
    print(f"   {load_info}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ingest historical PL data for model training")
    parser.add_argument(
        "--seasons",
        type=str,
        default=None,
        help="Comma-separated list of season start years (e.g., '2020,2021,2022')",
    )
    args = parser.parse_args()

    if not FOOTBALL_DATA_API_KEY:
        raise ValueError("FOOTBALL_DATA_API_KEY not set in .env!")

    seasons = None
    if args.seasons:
        seasons = [int(s.strip()) for s in args.seasons.split(",")]

    run_pipeline(seasons=seasons)
