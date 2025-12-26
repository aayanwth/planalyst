"""
PLanalyst — Dagster: Asset Definitions for Data Quality

Wraps Great Expectations checkpoints as Dagster assets.
Pipeline fails if quality checks don't pass.
"""

from dagster import AssetExecutionContext, Failure, MetadataValue, Output, asset


@asset(
    group_name="quality",
    description="Run Great Expectations quality checks on bronze.raw_matches",
    deps=["bronze_matches"],
    kinds={"python", "great_expectations"},
)
def quality_check_matches(context: AssetExecutionContext) -> Output:
    """Validate raw match data. Fails the pipeline if checks don't pass."""
    from planalyst.quality.match_expectations import validate_matches

    context.log.info("Running match data quality checks...")
    passed = validate_matches(fail_fast=True)
    context.log.info(f"Match quality checks: {'PASSED' if passed else 'FAILED'}")
    if not passed:
        raise Failure("Match data quality checks failed; pipeline halted.")

    return Output(
        value=passed,
        metadata={"passed": MetadataValue.bool(passed)},
    )


@asset(
    group_name="quality",
    description="Run Great Expectations quality checks on bronze.raw_news_articles",
    deps=["bronze_news"],
    kinds={"python", "great_expectations"},
)
def quality_check_news(context: AssetExecutionContext) -> Output:
    """Validate raw news data. Fails the pipeline if checks don't pass."""
    from planalyst.quality.news_expectations import validate_news

    context.log.info("Running news data quality checks...")
    passed = validate_news(fail_fast=True)
    context.log.info(f"News quality checks: {'PASSED' if passed else 'FAILED'}")
    if not passed:
        raise Failure("News data quality checks failed; pipeline halted.")

    return Output(
        value=passed,
        metadata={"passed": MetadataValue.bool(passed)},
    )
