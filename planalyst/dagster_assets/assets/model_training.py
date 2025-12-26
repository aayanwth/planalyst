"""
PLanalyst — Dagster: Asset Definition for Model Training

Separate, manually-triggered job for training the prediction model
on historical data. Not part of the per-matchweek pipeline.
"""

from dagster import AssetExecutionContext, MetadataValue, Output, asset


@asset(
    group_name="training",
    description=(
        "Load historical PL seasons into the training schema: football-data.org when an API key "
        "is configured, then a football-data.co.uk backfill for any season still missing"
    ),
    kinds={"python", "dlt", "postgres"},
)
def historical_data(context: AssetExecutionContext) -> Output:
    """Ingest historical match data for model training."""
    from planalyst.config import FOOTBALL_DATA_API_KEY
    from planalyst.pipelines.historical_matches import run_csv_backfill, run_pipeline

    if FOOTBALL_DATA_API_KEY:
        context.log.info("Ingesting historical match data from football-data.org...")
        run_pipeline()
    else:
        context.log.warning("FOOTBALL_DATA_API_KEY not set; relying on the CSV backfill only.")
    # The free API tier only reaches back ~3 seasons; fill the rest (seasons already loaded
    # are skipped, so the two sources never duplicate a match).
    loaded = run_csv_backfill()
    context.log.info(f"CSV backfill loaded seasons: {loaded or 'none needed'}")

    return Output(
        value=None,
        metadata={"csv_seasons_loaded": MetadataValue.text(", ".join(map(str, loaded)) or "none")},
    )


@asset(
    group_name="training",
    description="Build training features from historical data",
    deps=["historical_data"],
    kinds={"python", "pandas"},
)
def training_features(context: AssetExecutionContext) -> Output:
    """Build feature engineering for model training."""
    from planalyst.ml.features import build_training_features

    context.log.info("Building training features...")
    df = build_training_features()
    n_rows = len(df)
    context.log.info(f"Built {n_rows} training feature rows")

    return Output(
        value=n_rows,
        metadata={"rows": MetadataValue.int(n_rows)},
    )


@asset(
    group_name="training",
    description="Train the match prediction model on historical data",
    deps=["training_features"],
    kinds={"python", "sklearn", "mlflow"},
)
def trained_model(context: AssetExecutionContext) -> Output:
    """Train the prediction model."""
    from planalyst.ml.train import train_model

    context.log.info("Training prediction model...")
    # Default holdout = the latest season; metrics use earlier seasons only, then the model
    # is refit on everything (see ml/train.py).
    model, le, features = train_model()
    context.log.info("Model training complete.")

    return Output(
        value=None,
        metadata={
            "model_type": MetadataValue.text("XGBClassifier"),
            "features": MetadataValue.text(str(features)),
        },
    )
