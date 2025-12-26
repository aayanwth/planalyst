"""
PLanalyst — Great Expectations: Match Data Quality Suite

Validates bronze.raw_matches table:
- No null team names, matchday, dates
- Scores are non-negative integers
- Valid team names from the 2026-27 PL roster
- Expected number of fixtures per matchweek (10)
"""

import sys

from great_expectations.expectations import (
    ExpectColumnDistinctValuesToBeInSet,
    ExpectColumnValuesToBeBetween,
    ExpectColumnValuesToBeInSet,
    ExpectColumnValuesToNotBeNull,
    ExpectTableRowCountToBeBetween,
)
from sqlalchemy import create_engine, text

import great_expectations as gx
from planalyst.config import PL_TEAMS_API, SCHEMA_BRONZE, SQLALCHEMY_CONNECTION_STRING
from planalyst.quality.ge_config import (
    get_context,
    get_or_create_batch_definition,
    get_or_create_table_asset,
)

# All valid match statuses from football-data.org API
VALID_STATUSES = [
    "SCHEDULED",
    "TIMED",
    "LIVE",
    "IN_PLAY",
    "PAUSED",
    "FINISHED",
    "POSTPONED",
    "SUSPENDED",
    "CANCELLED",
    "AWARDED",
]


def build_match_suite(context) -> gx.ExpectationSuite:
    """Build the expectation suite for raw match data."""
    suite_name = "bronze_raw_matches_suite"

    # Create or get suite
    try:
        suite = context.suites.get(suite_name)
    except Exception:
        suite = context.suites.add(gx.ExpectationSuite(name=suite_name))

    # Clear existing expectations and re-add
    suite.expectations = []

    # ── Required columns must not be null ────────────────────────────────
    for col in ["home_team_name", "away_team_name", "matchday", "utc_date", "status"]:
        suite.expectations.append(
            ExpectColumnValuesToNotBeNull(column=col)
        )

    # Score nulls are expected for unplayed fixtures; negativity is checked in SQL.

    # ── Team names must be valid PL teams ────────────────────────────────
    for col in ["home_team_name", "away_team_name"]:
        suite.expectations.append(
            ExpectColumnDistinctValuesToBeInSet(
                column=col,
                value_set=PL_TEAMS_API,
            )
        )

    # ── Match status must be valid ───────────────────────────────────────
    suite.expectations.append(
        ExpectColumnValuesToBeInSet(
            column="status",
            value_set=VALID_STATUSES,
        )
    )

    # ── Matchday values between 1 and 38 ─────────────────────────────────
    suite.expectations.append(
        ExpectColumnValuesToBeBetween(
            column="matchday",
            min_value=1,
            max_value=38,
        )
    )

    # ── Total row count sanity check ─────────────────────────────────────
    # Full season = 380 matches. At minimum we expect at least 10 (1 matchweek)
    suite.expectations.append(
        ExpectTableRowCountToBeBetween(
            min_value=10,
            max_value=400,  # Some buffer for edge cases
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


def validate_matches(fail_fast: bool = True) -> bool:
    """
    Run the match data quality validation.

    Args:
        fail_fast: If True, raises an exception on validation failure.

    Returns:
        True if all checks pass, False otherwise.
    """
    context = get_context()
    suite = build_match_suite(context)

    data_asset = get_or_create_table_asset(
        context, "raw_matches_asset", "raw_matches", SCHEMA_BRONZE
    )
    batch_definition = get_or_create_batch_definition(data_asset, "raw_matches_batch")

    try:
        validation_definition = context.validation_definitions.get("validate_raw_matches")
    except Exception:
        validation_definition = context.validation_definitions.add(
            gx.ValidationDefinition(
                name="validate_raw_matches",
                data=batch_definition,
                suite=suite,
            )
        )

    try:
        checkpoint = context.checkpoints.get("match_quality_checkpoint")
    except Exception:
        checkpoint = context.checkpoints.add(
            gx.Checkpoint(
                name="match_quality_checkpoint",
                validation_definitions=[validation_definition],
            )
        )

    result = checkpoint.run()

    # SQL gates that GX column expectations cannot express cleanly
    engine = create_engine(SQLALCHEMY_CONNECTION_STRING)
    with engine.connect() as conn:
        negative_scores = conn.execute(text(f"""
            SELECT COUNT(*) FROM {SCHEMA_BRONZE}.raw_matches
            WHERE score_home < 0 OR score_away < 0
        """)).scalar()
        bad_matchweeks = conn.execute(text(f"""
            SELECT matchday, COUNT(*) AS n
            FROM {SCHEMA_BRONZE}.raw_matches
            GROUP BY matchday
            HAVING COUNT(*) <> 10
            ORDER BY matchday
        """)).fetchall()

    sql_ok = True
    if negative_scores:
        print(f"[FAIL] Found {negative_scores} matches with negative scorelines")
        sql_ok = False
    if bad_matchweeks:
        print(f"[FAIL] Matchweeks without exactly 10 fixtures: {bad_matchweeks}")
        sql_ok = False

    # Check results
    passed = bool(result.success) and sql_ok
    if passed:
        print("[OK] Match data quality checks PASSED")
    else:
        print("[FAIL] Match data quality checks FAILED!")
        # Print details of failed expectations
        for vr in result.run_results.values():
            for er in vr.results:
                if not er.success:
                    print(f"  FAILED: {er.expectation_config.type}")
                    print(f"    Result: {er.result}")

        if fail_fast:
            raise RuntimeError(
                "Match data quality checks failed! Pipeline halted. "
                "Fix data issues before proceeding."
            )

    return passed


if __name__ == "__main__":
    try:
        validate_matches(fail_fast=True)
    except RuntimeError as e:
        print(f"\n{e}")
        sys.exit(1)
