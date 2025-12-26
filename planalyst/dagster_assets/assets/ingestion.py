"""
PLanalyst — Dagster: Asset Definitions for Ingestion

Wraps the dlt pipelines as Dagster software-defined assets.
"""

from dagster import AssetExecutionContext, MetadataValue, Output, asset


@asset(
    group_name="bronze",
    description="Ingest Premier League match data from football-data.org into bronze.raw_matches",
    kinds={"python", "dlt", "postgres"},
)
def bronze_matches(context: AssetExecutionContext) -> Output:
    """Run the football matches dlt pipeline."""
    from planalyst.pipelines.football_matches import run_pipeline

    context.log.info("Starting football matches ingestion...")
    run_pipeline()
    context.log.info("Football matches ingestion complete.")

    return Output(
        value=None,
        metadata={
            "pipeline": MetadataValue.text("planalyst_football_matches"),
            "target": MetadataValue.text("bronze.raw_matches"),
        },
    )


@asset(
    group_name="bronze",
    description="Ingest PL news articles from the Guardian and GDELT (RSS fallback) into bronze.raw_news_articles",
    kinds={"python", "dlt", "postgres"},
)
def bronze_news(context: AssetExecutionContext) -> Output:
    """Run the news articles dlt pipeline."""
    from planalyst.pipelines.news_articles import run_pipeline

    context.log.info("Starting news articles ingestion...")
    run_pipeline()
    context.log.info("News articles ingestion complete.")

    return Output(
        value=None,
        metadata={
            "pipeline": MetadataValue.text("planalyst_news_articles"),
            "target": MetadataValue.text("bronze.raw_news_articles"),
        },
    )
