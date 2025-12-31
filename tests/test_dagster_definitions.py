"""The orchestration wiring: jobs, schedules, asset checks and the dbt-failure policy."""

import pytest

pytest.importorskip("dagster")

from planalyst.dagster_assets.definitions import defs  # noqa: E402


@pytest.fixture(scope="module")
def repo():
    return defs.get_repository_def()


def test_jobs_exist(repo):
    names = {job.name for job in repo.get_all_jobs()}
    assert {"matchweek_pipeline", "model_training_job", "news_ingestion_job"} <= names


def test_schedules_target_the_right_jobs_at_the_right_cadence(repo):
    schedules = {s.job_name: s for s in repo.schedule_defs}
    assert schedules["news_ingestion_job"].cron_schedule == "0 7 * * *"  # daily
    assert schedules["matchweek_pipeline"].cron_schedule == "0 9 * * 1"  # Mondays
    assert schedules["model_training_job"].cron_schedule == "0 6 1 * *"  # monthly
    assert all(s.execution_timezone == "UTC" for s in schedules.values())


def test_weekly_pipeline_scores_but_does_not_retrain(repo):
    """Retraining is its own job; the weekly job must not silently depend on it."""
    weekly = {key.to_user_string() for key in repo.get_job("matchweek_pipeline").asset_layer.executable_asset_keys}
    training = {key.to_user_string() for key in repo.get_job("model_training_job").asset_layer.executable_asset_keys}
    assert "model_scoring" in weekly and "dbt_transformations" in weekly
    assert not weekly & training
    assert training == {"historical_data", "training_features", "trained_model"}


def test_news_job_ingests_only_the_news(repo):
    keys = {k.to_user_string() for k in repo.get_job("news_ingestion_job").asset_layer.executable_asset_keys}
    assert keys == {"bronze_news"}


def test_prediction_sanity_checks_are_attached_to_model_scoring(repo):
    checks = {str(k.name): k.asset_key.to_user_string() for k in repo.asset_checks_defs_by_key}
    assert checks == {
        "title_probabilities_sum_to_one": "model_scoring",
        "every_upcoming_fixture_has_a_forecast": "model_scoring",
    }


def test_failing_dbt_tests_stop_the_pipeline_by_default(monkeypatch):
    import importlib

    import planalyst.config as config

    monkeypatch.delenv("PLANALYST_DBT_TESTS_FATAL", raising=False)
    assert importlib.reload(config).DBT_TESTS_FATAL is True
    monkeypatch.setenv("PLANALYST_DBT_TESTS_FATAL", "false")
    assert importlib.reload(config).DBT_TESTS_FATAL is False
    monkeypatch.delenv("PLANALYST_DBT_TESTS_FATAL")
    importlib.reload(config)
