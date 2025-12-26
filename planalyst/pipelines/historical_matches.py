"""
PLanalyst — dlt Pipeline: Historical Match Data (Training Dataset)

Ingests historical Premier League seasons from football-data.org into
a SEPARATE training schema. This data is ONLY used for model training
and must NEVER mix into the live bronze/silver/gold pipeline.

Scope: Multiple past seasons (as far back as the API supports).
"""

from datetime import datetime, timezone
from typing import Any, Generator

import dlt

from planalyst.config import (
    FOOTBALL_DATA_API_KEY,
    PL_SEASON,
    POSTGRES_CONNECTION_STRING,
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


@dlt.resource(
    name="historical_matches",
    write_disposition="merge",
    primary_key=["id"],
    columns={
        "id": {"data_type": "bigint"},
        "matchday": {"data_type": "bigint"},
        "home_team_id": {"data_type": "bigint", "nullable": True},
        "away_team_id": {"data_type": "bigint", "nullable": True},
        "score_home": {"data_type": "bigint", "nullable": True},
        "score_away": {"data_type": "bigint", "nullable": True},
        "season": {"data_type": "bigint"},
    },
)
def csv_historical_matches_resource(seasons: list[int]) -> Generator[dict[str, Any], None, None]:
    """
    Backfill from the football-data.co.uk result CSVs (no API key, no 3-season free-tier limit).

    Rows follow the API layout so downstream feature code is unchanged; clubs are renamed to
    the API spelling and `matchday` is a derived round number (see offline_data.assign_matchdays).
    Team ids and short names are not in the CSVs and stay null.
    """
    from planalyst.ml.offline_data import load_matches, to_api_names

    df = to_api_names(load_matches(seasons))
    ingested_at = datetime.now(timezone.utc).isoformat()
    for r in df.itertuples():
        yield {
            "id": int(r.id),
            "matchday": int(r.matchday),
            "status": "FINISHED",
            "utc_date": r.utc_date.tz_localize("UTC").isoformat(),
            "home_team_id": None,
            "home_team_name": r.home_team_name,
            "home_team_short": None,
            "away_team_id": None,
            "away_team_name": r.away_team_name,
            "away_team_short": None,
            "score_home": int(r.score_home),
            "score_away": int(r.score_away),
            "score_winner": r.score_winner,
            "season": int(r.season),
            "season_label": r.season_label,
            "ingested_at": ingested_at,
        }


def existing_seasons() -> set[int]:
    """Seasons already present in the training table (from any source)."""
    from sqlalchemy import create_engine, text

    from planalyst.config import SQLALCHEMY_CONNECTION_STRING

    try:
        with create_engine(SQLALCHEMY_CONNECTION_STRING).connect() as conn:
            rows = conn.execute(
                text(f"SELECT DISTINCT season FROM {SCHEMA_TRAINING}.historical_matches")
            ).all()
    except Exception:  # table not created yet
        return set()
    return {int(r[0]) for r in rows}


def run_csv_backfill(seasons: list[int] | None = None) -> list[int]:
    """
    Load CSV seasons into the training table. Seasons already present are skipped: the two
    sources use different match ids, so merging the same season would duplicate its matches.
    """
    wanted = seasons if seasons is not None else HISTORICAL_SEASONS
    present = existing_seasons()
    todo = [s for s in wanted if s not in present]
    skipped = sorted(set(wanted) & present)
    if skipped:
        print(f"  Skipping seasons already loaded: {skipped}")
    if not todo:
        print("  Nothing to load.")
        return []
    print(f"  Loading CSV seasons {todo} -> {SCHEMA_TRAINING}.historical_matches")
    print(f"   {create_pipeline().run(csv_historical_matches_resource(todo))}")
    return todo


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
    print("Load complete!")
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
    parser.add_argument(
        "--source",
        choices=["api", "csv"],
        default="api",
        help="api: football-data.org (needs a key, free tier ~3 seasons). "
        "csv: football-data.co.uk results, backfills seasons not already loaded.",
    )
    args = parser.parse_args()

    seasons = None
    if args.seasons:
        seasons = [int(s.strip()) for s in args.seasons.split(",")]

    if args.source == "csv":
        run_csv_backfill(seasons)
    else:
        if not FOOTBALL_DATA_API_KEY:
            raise ValueError("FOOTBALL_DATA_API_KEY not set in .env!")
        run_pipeline(seasons=seasons)
