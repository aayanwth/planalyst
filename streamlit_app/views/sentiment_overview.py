"""
PLanalyst — Streamlit Page: Matchweek Sentiment

How the press covered each club in a matchweek, and whether that tracked the results.
Clubs with thin coverage are shown as blank, never ranked.
"""

import pandas as pd
import streamlit as st

from streamlit_app import charts, theme
from streamlit_app.utils import (
    get_matchweek_summaries,
    get_matchweek_summary,
    get_title_predictions,
    latest_matchweek,
)


def render() -> None:
    latest = latest_matchweek()
    theme.page_header(
        "Matchweek sentiment",
        "News coverage scored by a RoBERTa sentiment model, grouped by club and the matchweek it was published in.",
    )

    matchweek = st.slider("Matchweek", min_value=1, max_value=max(latest, 2), value=latest)
    data = get_matchweek_summary(matchweek)

    if data is None:
        theme.api_error()
        return
    if "error" in data:
        theme.empty_state(f"No data for matchweek {matchweek}", "That matchweek hasn't been played or scored yet.")
        return

    standings = pd.DataFrame(data["standings"])
    summary = data["summary"]
    covered = int((standings["article_count"] >= charts.MIN_ARTICLES).sum())
    predictions = (get_title_predictions() or {}).get("predictions", [])
    colors = theme.team_colors([p["team"] for p in sorted(predictions, key=lambda p: -p["win_probability"])])

    theme.stat_strip(
        [
            ("Articles scored", theme.counted(summary["total_articles"]), "attributed to this matchweek"),
            ("Average sentiment", charts._signed(summary["avg_sentiment"], 3), "−1 negative … +1 positive"),
            ("Clubs with enough coverage", theme.counted(covered, f" of {len(standings)}"), f"at least {charts.MIN_ARTICLES} articles each"),
        ]
    )

    if summary["total_articles"] == 0:
        theme.empty_state("No articles for this matchweek", "Results are shown below, but there is no sentiment to chart yet.")
    elif covered == 0:
        st.info(f"No club has {charts.MIN_ARTICLES}+ articles this matchweek, so sentiment charts are held back rather than showing noise.")

    left, right = st.columns([7, 5], gap="medium")
    with left:
        with theme.panel("Sentiment by club", f"clubs with {charts.MIN_ARTICLES}+ articles"):
            fig = charts.sentiment_bars(standings, colors=colors)
            if fig is None:
                theme.empty_state("Not enough coverage", "Pick a later matchweek, or wait for more articles to be ingested.")
            else:
                theme.show(fig, key="mw-bars")
    with right:
        with theme.panel("Who the articles were about", "title contenders in their ink"):
            fig = charts.coverage_donut(standings, colors, top=6, height=340)
            if fig is None:
                theme.empty_state("No coverage", "No articles were attributed to any club this matchweek.")
            else:
                theme.show(fig, key="mw-donut")

    left, right = st.columns([5, 7], gap="medium")
    with left:
        with theme.panel("Sentiment and results", "one dot per club"):
            fig = charts.sentiment_vs_points(standings)
            if fig is None:
                theme.empty_state("Not enough clubs to compare", "This view needs at least four clubs with enough coverage.")
            else:
                theme.show(fig, key="mw-scatter")
    with right:
        with theme.panel("Sentiment across the season", f"blank = under {charts.MIN_ARTICLES} articles"):
            fig = charts.sentiment_heatmap(get_matchweek_summaries(latest))
            if fig is None:
                theme.empty_state("Nothing to map yet", "No club has enough coverage in any matchweek.")
            else:
                theme.show(fig, key="mw-heat")

    with theme.panel("League table through this matchweek"):
        table = standings.sort_values(["cumulative_points", "cumulative_gd"], ascending=False).reset_index(drop=True)
        table.index = table.index + 1
        shown = table[["team", "result", "goals_for", "goals_against", "points", "cumulative_points", "cumulative_gd", "avg_sentiment", "article_count"]]
        shown.columns = ["Team", "Result", "GF", "GA", "Pts (week)", "Pts", "GD", "Sentiment", "Articles"]
        shown = shown.copy()
        shown.insert(0, "Crest", [theme.crest_url(t) for t in shown["Team"]])
        thin = shown["Articles"] < charts.MIN_ARTICLES
        shown["Sentiment"] = [("—" if is_thin else charts._signed(v, 3)) for v, is_thin in zip(shown["Sentiment"], thin)]  # thin coverage: a dash, not a number
        st.dataframe(
            shown, width="stretch", height=420,
            column_config={"Crest": st.column_config.ImageColumn("", width="small"), "Articles": st.column_config.ProgressColumn(min_value=0, max_value=max(int(shown["Articles"].max()), 1), format="%d")},
        )
        st.markdown(
            f'<div class="note">Sentiment shows a dash for clubs with fewer than {charts.MIN_ARTICLES} articles.</div>',
            unsafe_allow_html=True,
        )
