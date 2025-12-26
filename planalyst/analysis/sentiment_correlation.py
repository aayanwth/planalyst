"""
PLanalyst — Does media sentiment relate to match performance?

Reads gold.fact_team_sentiment_performance (one row per team per matchweek) and
tests three relationships with Spearman rank correlation:

  1. same_mw      sentiment in MW n   vs  points in MW n
                  (articles are attributed to the next match, so this is
                  pre-match sentiment vs the result that followed)
  2. pre_to_gd    sentiment in MW n   vs  goal difference in MW n
  3. result_to_next  points in MW n   vs  sentiment in MW n+1
                  (do results drive subsequent coverage - reverse direction)

Team-matchweeks with no articles are dropped: the fact table fills missing
sentiment with 0, which would otherwise be confused with "neutral coverage".

How articles reach a team-matchweek (dbt model silver_article_teams): an article counts for each
club it names, attributed to that club's NEXT fixture at publication time, so it is always
pre-match for the match it is compared with. An opponent named in a head-to-head article gets the
sign inverted, and round-ups naming three or more clubs are excluded. The fact table only holds
matchweeks that have been played, so coverage of upcoming fixtures appears once they finish.

Run:  python -m planalyst.analysis.sentiment_correlation
"""

from pathlib import Path

import pandas as pd
from scipy import stats
from sqlalchemy import create_engine

from planalyst.config import PROJECT_ROOT, SQLALCHEMY_CONNECTION_STRING

FACT_QUERY = """
    SELECT team_name, matchweek_number, points, goal_difference,
           avg_sentiment_score, article_count
    FROM public_gold.fact_team_sentiment_performance
"""
MIN_PAIRS = 8  # below this a correlation is not worth reporting
REPORT_PATH = PROJECT_ROOT / "docs" / "sentiment_correlation.md"


def load_fact() -> pd.DataFrame:
    engine = create_engine(SQLALCHEMY_CONNECTION_STRING)
    return pd.read_sql(FACT_QUERY, engine)


def add_next_matchweek_sentiment(df: pd.DataFrame) -> pd.DataFrame:
    """Attach the team's sentiment/article_count from the following matchweek."""
    nxt = df[["team_name", "matchweek_number", "avg_sentiment_score", "article_count"]].copy()
    nxt["matchweek_number"] -= 1
    nxt = nxt.rename(
        columns={
            "avg_sentiment_score": "next_sentiment",
            "article_count": "next_article_count",
        }
    )
    return df.merge(nxt, on=["team_name", "matchweek_number"], how="left")


def _spearman(x: pd.Series, y: pd.Series) -> dict:
    n = len(x)
    if n < MIN_PAIRS or x.nunique() < 2 or y.nunique() < 2:
        return {"n": n, "rho": None, "p_value": None}
    rho, p = stats.spearmanr(x, y)
    return {"n": n, "rho": float(rho), "p_value": float(p)}


def compute_correlations(df: pd.DataFrame) -> pd.DataFrame:
    df = add_next_matchweek_sentiment(df)
    covered = df[df["article_count"] > 0]
    next_covered = df[df["next_article_count"].fillna(0) > 0]

    tests = [
        ("Sentiment MW n vs points MW n", covered["avg_sentiment_score"], covered["points"]),
        (
            "Sentiment MW n vs goal diff MW n",
            covered["avg_sentiment_score"],
            covered["goal_difference"],
        ),
        (
            "Points MW n vs sentiment MW n+1",
            next_covered["points"],
            next_covered["next_sentiment"],
        ),
    ]
    rows = [{"relationship": name, **_spearman(x, y)} for name, x, y in tests]
    return pd.DataFrame(rows)


def to_markdown(results: pd.DataFrame, df: pd.DataFrame) -> str:
    lines = [
        "# Sentiment vs match performance",
        "",
        f"Matchweeks analysed: {df['matchweek_number'].nunique()} · "
        f"team-matchweeks with coverage: {int((df['article_count'] > 0).sum())} · "
        f"articles: {int(df['article_count'].sum())}",
        "",
        "| Relationship | n | Spearman rho | p-value |",
        "|---|---|---|---|",
    ]
    for r in results.itertuples():
        if pd.isna(r.rho):
            lines.append(f"| {r.relationship} | {r.n} | insufficient data | - |")
        else:
            lines.append(f"| {r.relationship} | {r.n} | {r.rho:+.3f} | {r.p_value:.3f} |")
    lines += [
        "",
        "p < 0.05 would suggest a real association. With few matchweeks the test has "
        "little power, so a non-significant result is not evidence of no effect.",
    ]
    return "\n".join(lines) + "\n"


def main(report_path: Path = REPORT_PATH) -> None:
    df = load_fact()
    results = compute_correlations(df)
    report = to_markdown(results, df)
    report_path.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
