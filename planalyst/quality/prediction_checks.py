"""
PLanalyst — Sanity checks on the model's outputs (run as Dagster asset checks after scoring).

They query the Gold tables directly so they also catch problems that unit tests cannot: a
stale model file, a simulation that dropped teams, or fixtures that never received a forecast.
"""

from sqlalchemy import text

from planalyst.config import PL_SEASON, SCHEMA_BRONZE, SCHEMA_GOLD

PROBABILITY_TOLERANCE = 0.01  # win probabilities are rounded to 4 d.p. per team


def title_probability_total(engine) -> float:
    """Sum of title probabilities in the latest run (should be 1.0)."""
    with engine.connect() as conn:
        total = conn.execute(
            text(f"SELECT COALESCE(SUM(win_probability), 0) FROM {SCHEMA_GOLD}.gold_title_predictions")
        ).scalar()
    return float(total or 0.0)


def probabilities_sum_to_one(total: float, tolerance: float = PROBABILITY_TOLERANCE) -> bool:
    return abs(total - 1.0) <= tolerance


def missing_fixture_forecasts(engine, season: int = PL_SEASON) -> int:
    """Unplayed fixtures of the season that have no stored forecast."""
    with engine.connect() as conn:
        missing = conn.execute(
            text(
                f"SELECT COUNT(*) FROM {SCHEMA_BRONZE}.raw_matches m "
                f"LEFT JOIN {SCHEMA_GOLD}.fixture_predictions f ON f.match_id = m.id "
                "WHERE m.status != 'FINISHED' AND m.season = :season AND f.match_id IS NULL"
            ),
            {"season": season},
        ).scalar()
    return int(missing or 0)
