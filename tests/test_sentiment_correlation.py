import numpy as np
import pandas as pd

from planalyst.analysis.sentiment_correlation import (
    add_next_matchweek_sentiment,
    compute_correlations,
    to_markdown,
)


def _fact(n_teams=10, n_weeks=3, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for t in range(n_teams):
        for w in range(1, n_weeks + 1):
            pts = int(rng.choice([0, 1, 3]))
            rows.append(
                {
                    "team_name": f"T{t}",
                    "matchweek_number": w,
                    "points": pts,
                    "goal_difference": pts - 1,
                    # sentiment perfectly tracks points -> strong positive rho
                    "avg_sentiment_score": pts / 3,
                    "article_count": 5,
                }
            )
    return pd.DataFrame(rows)


def test_next_matchweek_shift():
    df = add_next_matchweek_sentiment(_fact(n_teams=1))
    mw1 = df[df.matchweek_number == 1].iloc[0]
    mw2 = df[df.matchweek_number == 2].iloc[0]
    assert mw1.next_sentiment == mw2.avg_sentiment_score
    assert np.isnan(df[df.matchweek_number == 3].iloc[0].next_sentiment)


def test_detects_perfect_association():
    res = compute_correlations(_fact()).set_index("relationship")
    assert res.loc["Sentiment MW n vs points MW n", "rho"] > 0.99


def test_insufficient_data_returns_none():
    res = compute_correlations(_fact(n_teams=2, n_weeks=2))
    assert res["rho"].isna().all()
    assert "insufficient data" in to_markdown(res, _fact(n_teams=2, n_weeks=2))


def test_zero_article_rows_are_excluded():
    df = _fact()
    df.loc[df.index[:20], "article_count"] = 0
    res = compute_correlations(df)
    assert res.loc[0, "n"] == len(df) - 20
