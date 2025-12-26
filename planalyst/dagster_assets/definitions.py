"""
PLanalyst — Dagster: Main Definitions

Entry point for Dagster. Registers all assets, jobs, and resources.
Run with: dagster dev -m planalyst.dagster_assets.definitions
"""

from dagster import Definitions, load_asset_checks_from_modules, load_assets_from_modules

from planalyst.dagster_assets.assets import (
    ingestion,
    model_scoring,
    model_training,
    nlp_scoring,
    quality,
    transformations,
)
from planalyst.dagster_assets.jobs import matchweek_pipeline, model_training_job, news_ingestion_job
from planalyst.dagster_assets.resources import (
    FootballAPIResource,
    GuardianAPIResource,
    PostgresResource,
)
from planalyst.dagster_assets.schedules import all_schedules

# Load all assets from the asset modules
all_assets = load_assets_from_modules([
    ingestion,
    quality,
    transformations,
    nlp_scoring,
    model_scoring,
    model_training,
])

all_checks = load_asset_checks_from_modules([model_scoring])

defs = Definitions(
    assets=all_assets,
    asset_checks=all_checks,
    jobs=[matchweek_pipeline, model_training_job, news_ingestion_job],
    schedules=all_schedules,
    resources={
        "postgres": PostgresResource(),
        "football_api": FootballAPIResource(),
        "guardian_api": GuardianAPIResource(),
    },
)
