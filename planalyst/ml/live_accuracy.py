"""
PLanalyst — Live accuracy tracker.

Scores the forecasts the pipeline stored BEFORE each match (gold.fixture_predictions) against
the results that arrived afterwards (bronze.raw_matches). Because a forecast is frozen once its
match is played, this is a genuine out-of-sample record of how the model is doing this season.

The same matches are also scored with a naive baseline (the historical home/draw/away
frequencies), so the numbers can be read as "better or worse than knowing nothing".

Numpy/pandas/SQLAlchemy only, so the API image can use it without scikit-learn.
"""

import numpy as np
import pandas as pd
from sqlalchemy import text

from planalyst.config import SCHEMA_BRONZE, SCHEMA_GOLD, SCHEMA_TRAINING
from planalyst.ml.metrics import outcome_index, summarize

MIN_MATCHES_FOR_COMPARISON = 1


def load_scored_matches(engine) -> pd.DataFrame:
    """Forecasts joined to finished results (one row per match that has been played)."""
    query = text(f"""
        SELECT fp.match_id, fp.matchday, fp.home_team_name, fp.away_team_name,
               fp.p_home, fp.p_draw, fp.p_away, m.score_home, m.score_away
        FROM {SCHEMA_GOLD}.fixture_predictions fp
        JOIN {SCHEMA_BRONZE}.raw_matches m ON m.id = fp.match_id
        WHERE m.status = 'FINISHED' AND m.score_home IS NOT NULL AND m.score_away IS NOT NULL
        ORDER BY fp.matchday, fp.match_id
    """)
    columns = [
        "match_id", "matchday", "home_team_name", "away_team_name",
        "p_home", "p_draw", "p_away", "score_home", "score_away",
    ]  # fmt: skip
    # Read rows directly: pandas.read_sql would wrap a missing-table error in its own exception
    # type, which the API could no longer recognise as "pipeline has not run yet".
    with engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(query).mappings().all()]
    return pd.DataFrame(rows, columns=columns)


def historical_outcome_frequencies(engine) -> np.ndarray | None:
    """[P(home), P(draw), P(away)] over the training history, or None if it is unavailable."""
    query = text(f"""
        SELECT
            SUM(CASE WHEN score_home > score_away THEN 1 ELSE 0 END),
            SUM(CASE WHEN score_home = score_away THEN 1 ELSE 0 END),
            SUM(CASE WHEN score_home < score_away THEN 1 ELSE 0 END)
        FROM {SCHEMA_TRAINING}.historical_matches
        WHERE score_home IS NOT NULL
    """)
    try:
        with engine.connect() as conn:
            counts = np.array(conn.execute(query).one(), dtype=float)
    except Exception:
        return None
    total = counts.sum()
    return counts / total if total > 0 else None


def compute_live_accuracy(engine) -> dict:
    """Overall and per-matchweek metrics for the stored forecasts, plus the naive baseline."""
    scored = load_scored_matches(engine)
    if scored.empty:
        return {"matches_scored": 0, "model": None, "baseline": None, "by_matchweek": []}

    probs = scored[["p_home", "p_draw", "p_away"]].to_numpy(dtype=float)
    y = outcome_index(scored["score_home"], scored["score_away"])

    prior = historical_outcome_frequencies(engine)
    baseline = None if prior is None else summarize(np.tile(prior, (len(y), 1)), y)

    by_week = []
    for matchday, idx in scored.groupby("matchday").indices.items():
        week = summarize(probs[idx], y[idx])
        by_week.append({"matchweek": int(matchday), **week})

    return {
        "matches_scored": int(len(y)),
        "model": summarize(probs, y),
        "baseline": baseline,
        "by_matchweek": by_week,
    }
