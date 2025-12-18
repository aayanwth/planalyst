"""
PLanalyst — Dagster: Asset Definition for Model Scoring

Applies the trained prediction model to current live data.
(Part of the per-matchweek job, not model training.)
"""

from dagster import asset, AssetExecutionContext, Output, MetadataValue


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
