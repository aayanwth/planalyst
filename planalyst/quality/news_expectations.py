"""
PLanalyst — Great Expectations: News Data Quality Suite

Validates bronze.raw_news_articles table:
- No null titles, published dates, team queries
- Team queries are valid PL team names
- Dates are within the season window
"""

import sys
from datetime import datetime
from email.utils import parsedate_to_datetime

from great_expectations.expectations import (
    ExpectColumnValuesToBeInSet,
    ExpectColumnValuesToNotBeNull,
    ExpectTableRowCountToBeBetween,
)
from sqlalchemy import create_engine, text

import great_expectations as gx
from planalyst.config import (
    PL_SEASON_START_DATE,
    PL_TEAMS_SHORT,
    SCHEMA_BRONZE,
    SQLALCHEMY_CONNECTION_STRING,
)

# Also include TEAM_SEARCH_QUERIES values which may differ slightly
from planalyst.pipelines.news_articles import TEAM_SEARCH_QUERIES
from planalyst.quality.ge_config import (
    get_context,
    get_or_create_batch_definition,
    get_or_create_table_asset,
)

VALID_TEAM_QUERIES = list(set(TEAM_SEARCH_QUERIES.values()) | set(PL_TEAMS_SHORT))


def _parse_published_date(value):
    if value is None:
        return None
    text_value = str(value).strip()
    try:
        if len(text_value) >= 10 and text_value[4] == "-":
            return datetime.fromisoformat(text_value.replace("Z", "+00:00")).date()
        return parsedate_to_datetime(text_value).date()
    except Exception:
        return None


def build_news_suite(context) -> gx.ExpectationSuite:
    """Build the expectation suite for raw news articles."""
    suite_name = "bronze_raw_news_articles_suite"

    try:
        suite = context.suites.get(suite_name)
    except Exception:
        suite = context.suites.add(gx.ExpectationSuite(name=suite_name))

    suite.expectations = []

    # ── Required columns must not be null ────────────────────────────────
    for col in ["title", "published_at", "team_query"]:
        suite.expectations.append(
            ExpectColumnValuesToNotBeNull(column=col)
        )

    # ── URL must not be null (primary key) ───────────────────────────────
    suite.expectations.append(
        ExpectColumnValuesToNotBeNull(column="url")
    )

    # ── Team query must be valid ─────────────────────────────────────────
    suite.expectations.append(
        ExpectColumnValuesToBeInSet(
            column="team_query",
            value_set=VALID_TEAM_QUERIES,
        )
    )

    # ── Row count sanity ─────────────────────────────────────────────────
    # We should have at least some articles
    suite.expectations.append(
        ExpectTableRowCountToBeBetween(
            min_value=1,
            max_value=100000,
        )
    )

    try:
        suite.save()
    except Exception:
        try:
            suite = context.suites.add(suite)
        except Exception:
            pass
    return suite


def validate_news(fail_fast: bool = True) -> bool:
    """
    Run the news data quality validation.

    Args:
        fail_fast: If True, raises an exception on validation failure.

    Returns:
        True if all checks pass, False otherwise.
    """
    context = get_context()
    suite = build_news_suite(context)

    data_asset = get_or_create_table_asset(
        context, "raw_news_articles_asset", "raw_news_articles", SCHEMA_BRONZE
    )
    batch_definition = get_or_create_batch_definition(data_asset, "raw_news_batch")

    try:
        validation_definition = context.validation_definitions.get("validate_raw_news")
    except Exception:
        validation_definition = context.validation_definitions.add(
            gx.ValidationDefinition(
                name="validate_raw_news",
                data=batch_definition,
                suite=suite,
            )
        )

    try:
        checkpoint = context.checkpoints.get("news_quality_checkpoint")
    except Exception:
        checkpoint = context.checkpoints.add(
            gx.Checkpoint(
                name="news_quality_checkpoint",
                validation_definitions=[validation_definition],
            )
        )

    result = checkpoint.run()

    engine = create_engine(SQLALCHEMY_CONNECTION_STRING)
    with engine.connect() as conn:
        published = conn.execute(text(f"""
            SELECT url, published_at FROM {SCHEMA_BRONZE}.raw_news_articles
        """)).fetchall()

    season_start = datetime.fromisoformat(PL_SEASON_START_DATE).date()
    too_old = []
    for url, published_at in published:
        parsed = _parse_published_date(published_at)
        if parsed is not None and parsed < season_start:
            too_old.append((url, published_at))

    sql_ok = True
    if too_old:
        print(f"[FAIL] {len(too_old)} articles dated before season start {PL_SEASON_START_DATE}")
        sql_ok = False

    passed = bool(result.success) and sql_ok
    if passed:
        print("[OK] News data quality checks PASSED")
    else:
        print("[FAIL] News data quality checks FAILED!")
        for vr in result.run_results.values():
            for er in vr.results:
                if not er.success:
                    print(f"  FAILED: {er.expectation_config.type}")
                    print(f"    Result: {er.result}")

        if fail_fast:
            raise RuntimeError(
                "News data quality checks failed! Pipeline halted. "
                "Fix data issues before proceeding."
            )

    return passed


if __name__ == "__main__":
    try:
        validate_news(fail_fast=True)
    except RuntimeError as e:
        print(f"\n{e}")
        sys.exit(1)
