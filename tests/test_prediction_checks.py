import pytest
from sqlalchemy import text

from planalyst.quality.prediction_checks import (
    missing_fixture_forecasts,
    probabilities_sum_to_one,
    title_probability_total,
)


def test_probability_total_tolerance():
    assert probabilities_sum_to_one(1.0)
    assert probabilities_sum_to_one(0.9995)
    assert not probabilities_sum_to_one(0.95)  # a team dropped out of the simulation
    assert not probabilities_sum_to_one(0.0)  # empty table


def test_title_probability_total_reads_the_gold_table(sqlite_engine):
    with sqlite_engine.begin() as conn:
        conn.execute(text("CREATE TABLE gold.gold_title_predictions (win_probability REAL)"))
        assert title_probability_total(sqlite_engine) == 0.0  # empty table
        conn.execute(text("INSERT INTO gold.gold_title_predictions VALUES (0.6), (0.4)"))
    assert title_probability_total(sqlite_engine) == pytest.approx(1.0)


def test_missing_forecasts_counts_only_unplayed_fixtures_of_the_season(sqlite_engine):
    with sqlite_engine.begin() as conn:
        conn.execute(text("CREATE TABLE bronze.raw_matches (id INT, status TEXT, season INT)"))
        conn.execute(text("CREATE TABLE gold.fixture_predictions (match_id INT)"))
        conn.execute(
            text(
                "INSERT INTO bronze.raw_matches VALUES "
                "(1,'FINISHED',2026),(2,'TIMED',2026),(3,'TIMED',2026),(4,'TIMED',2025)"
            )
        )
        conn.execute(text("INSERT INTO gold.fixture_predictions VALUES (2)"))
    # match 1 is played, 2 has a forecast, 4 belongs to another season; only 3 is missing
    assert missing_fixture_forecasts(sqlite_engine, season=2026) == 1
    with sqlite_engine.begin() as conn:
        conn.execute(text("INSERT INTO gold.fixture_predictions VALUES (3)"))
    assert missing_fixture_forecasts(sqlite_engine, season=2026) == 0
