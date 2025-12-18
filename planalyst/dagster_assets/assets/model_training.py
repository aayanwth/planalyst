"""
PLanalyst — Dagster: Asset Definition for Model Training

Separate, manually-triggered job for training the prediction model
on historical data. Not part of the per-matchweek pipeline.
"""

from dagster import asset, AssetExecutionContext, Output, MetadataValue


@asset(
    group_name="training",
    description="Ingest historical PL seasons into training schema",
    kinds={"python", "dlt", "postgres"},
)
def historical_data(context: AssetExecutionContext) -> Output:
    """Ingest historical match data for model training."""
    from planalyst.pipelines.historical_matches import run_pipeline

    context.log.info("Ingesting historical match data...")
    run_pipeline()
    context.log.info("Historical data ingestion complete.")

    return Output(value=None)


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
    model, le, features = train_model(holdout_season=2024)
    context.log.info("Model training complete.")

    return Output(
        value=None,
        metadata={
            "model_type": MetadataValue.text("XGBClassifier"),
            "features": MetadataValue.text(str(features)),
        },
    )
