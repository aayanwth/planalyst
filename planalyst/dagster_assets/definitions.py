"""
PLanalyst — Dagster: Main Definitions

Entry point for Dagster. Registers all assets, jobs, and resources.
Run with: dagster dev -m planalyst.dagster_assets.definitions
"""

from dagster import Definitions, load_assets_from_modules

from planalyst.dagster_assets.assets import (
    ingestion,
    quality,
    transformations,
    nlp_scoring,
    model_scoring,
    model_training,
)
from planalyst.dagster_assets.jobs import matchweek_pipeline, model_training_job
from planalyst.dagster_assets.resources import (
    PostgresResource,
    FootballAPIResource,
    NewsAPIResource,
)

# Load all assets from the asset modules
all_assets = load_assets_from_modules([
    ingestion,
    quality,
    transformations,
    nlp_scoring,
    model_scoring,
    model_training,
])

defs = Definitions(
    assets=all_assets,
    jobs=[matchweek_pipeline, model_training_job],
    resources={
        "postgres": PostgresResource(),
        "football_api": FootballAPIResource(),
        "news_api": NewsAPIResource(),
    },
)
