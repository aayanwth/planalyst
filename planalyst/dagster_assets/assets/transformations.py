"""
PLanalyst — Dagster: Asset Definitions for dbt Transformations

Runs dbt seed + run as Dagster assets (Silver and Gold layers).
"""

from pathlib import Path

from dagster import AssetExecutionContext, MetadataValue, Output, asset

from planalyst.config import DBT_TESTS_FATAL

DBT_PROJECT_DIR = str(Path(__file__).resolve().parent.parent.parent.parent / "dbt_project")


def _run_dbt(args: list[str], context: AssetExecutionContext, fatal: bool = True) -> bool:
    from dbt.cli.main import dbtRunner

    runner = dbtRunner()
    result = runner.invoke(args + ["--profiles-dir", DBT_PROJECT_DIR, "--project-dir", DBT_PROJECT_DIR])
    if not result.success:
        err = getattr(result, "exception", None) or result
        msg = f"dbt {' '.join(args)} failed: {err}"
        if fatal:
            raise RuntimeError(msg)
        context.log.warning(msg)
        return False
    context.log.info(f"dbt {' '.join(args)} succeeded")
    return True


@asset(
    group_name="silver",
    description="Run dbt seed + models to create Silver and Gold layer tables",
    deps=["quality_check_matches", "quality_check_news"],
    kinds={"python", "dbt", "postgres"},
)
def dbt_transformations(context: AssetExecutionContext) -> Output:
    """Run dbt seed and dbt run to build Silver + Gold models."""
    from planalyst.nlp.sentiment import ensure_scores_table

    context.log.info(f"Running dbt in {DBT_PROJECT_DIR}")
    # The gold fact model joins silver.silver_sentiment_scores, which NLP scoring
    # (a downstream asset) normally creates; make sure it exists on a fresh DB.
    ensure_scores_table()
    _run_dbt(["seed"], context)
    _run_dbt(["run"], context)
    # Stale source data is a warning (the daily news job may simply not have run yet); failing
    # dbt tests stop the pipeline unless PLANALYST_DBT_TESTS_FATAL=false.
    _run_dbt(["source", "freshness"], context, fatal=False)
    _run_dbt(["test"], context, fatal=DBT_TESTS_FATAL)

    return Output(
        value=None,
        metadata={
            "dbt_project": MetadataValue.text(DBT_PROJECT_DIR),
            "seed_status": MetadataValue.text("OK"),
            "run_status": MetadataValue.text("OK"),
        },
    )


@asset(
    group_name="gold",
    description="Rebuild gold fact table after NLP scores are written",
    deps=["nlp_sentiment_scoring"],
    kinds={"python", "dbt", "postgres"},
)
def gold_fact_refresh(context: AssetExecutionContext) -> Output:
    """Re-run gold models so fact_team_sentiment_performance includes sentiment."""
    context.log.info("Refreshing gold models with sentiment scores...")
    _run_dbt(["run", "--select", "fact_team_sentiment_performance"], context)
    # The fact table was rebuilt after the first `dbt test`, so test it again.
    _run_dbt(
        ["test", "--select", "fact_team_sentiment_performance"], context, fatal=DBT_TESTS_FATAL
    )
    return Output(value=None, metadata={"status": MetadataValue.text("OK")})
