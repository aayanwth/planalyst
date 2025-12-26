"""
PLanalyst — Dagster: Asset Definition for Model Scoring

Applies the trained prediction model to current live data.
(Part of the per-matchweek job, not model training.)
"""

from dagster import (
    AssetCheckResult,
    AssetExecutionContext,
    MetadataValue,
    Output,
    asset,
    asset_check,
)


@asset(
    group_name="gold",
    description="Score live 2026-27 data with the trained model to update title predictions",
    deps=["gold_fact_refresh"],
    kinds={"python", "sklearn", "mlflow"},
)
def model_scoring(context: AssetExecutionContext) -> Output:
    """Apply trained model to live data and update gold_title_predictions."""
    from planalyst.ml.predict import run_predictions

    context.log.info("Running model scoring on live data...")
    predictions = run_predictions()
    n_teams = len(predictions)
    if n_teams == 0:
        context.log.warning("No predictions generated (no finished matches yet?).")
    else:
        context.log.info(f"Generated predictions for {n_teams} teams")

    return Output(
        value=n_teams,
        metadata={
            "teams_predicted": MetadataValue.int(n_teams),
            "top_team": MetadataValue.text(
                predictions.iloc[0]["team_name"] if not predictions.empty else "N/A"
            ),
        },
    )


@asset_check(
    asset=model_scoring,
    description="Title probabilities across all teams must sum to 1 (a dropped team or a stale table breaks this)",
)
def title_probabilities_sum_to_one() -> AssetCheckResult:
    from sqlalchemy import create_engine

    from planalyst.config import SQLALCHEMY_CONNECTION_STRING
    from planalyst.quality.prediction_checks import (
        probabilities_sum_to_one,
        title_probability_total,
    )

    total = title_probability_total(create_engine(SQLALCHEMY_CONNECTION_STRING))
    return AssetCheckResult(
        passed=probabilities_sum_to_one(total), metadata={"total_probability": total}
    )


@asset_check(
    asset=model_scoring,
    description="Every unplayed fixture of the season must have a stored forecast",
)
def every_upcoming_fixture_has_a_forecast() -> AssetCheckResult:
    from sqlalchemy import create_engine

    from planalyst.config import SQLALCHEMY_CONNECTION_STRING
    from planalyst.quality.prediction_checks import missing_fixture_forecasts

    missing = missing_fixture_forecasts(create_engine(SQLALCHEMY_CONNECTION_STRING))
    return AssetCheckResult(passed=missing == 0, metadata={"fixtures_without_forecast": missing})
