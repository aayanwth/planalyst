"""
PLanalyst — Dagster: Job Definitions

Defines two jobs:
1. matchweek_pipeline: Per-matchweek automated job (ingest → quality → dbt → NLP → scoring)
2. model_training_job: Manual trigger for model (re)training on historical data
"""

from dagster import AssetSelection, define_asset_job

# ── Per-Matchweek Pipeline ───────────────────────────────────────────────────
# Runs every matchweek: ingestion → quality checks → dbt → NLP → model scoring
matchweek_pipeline = define_asset_job(
    name="matchweek_pipeline",
    description="Full per-matchweek pipeline: ingest → quality → transform → NLP → predict",
    selection=AssetSelection.groups("bronze", "quality", "silver", "gold"),
)

# ── Daily news ingestion ─────────────────────────────────────────────────────
# RSS feeds only expose recent items, so news must be collected daily or articles are lost.
news_ingestion_job = define_asset_job(
    name="news_ingestion_job",
    description="Ingest news into bronze only (no quality gate, no transformation)",
    selection=AssetSelection.assets("bronze_news"),
)

# ── Model Training Job ──────────────────────────────────────────────────────
# Manually triggered: ingest historical → features → train model
model_training_job = define_asset_job(
    name="model_training_job",
    description="Train/retrain the prediction model on historical data (manual trigger)",
    selection=AssetSelection.groups("training"),
)
