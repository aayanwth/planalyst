"""
PLanalyst — Streamlit Page: Overview

The one-screen answer: who is favourite for the title, how the probability is split, what the
press is saying this week and what the model expects next.
"""

from datetime import datetime

import pandas as pd
import streamlit as st

from streamlit_app import charts, theme
from streamlit_app.utils import (
    get_fixture_forecasts,
    get_matchweek_summaries,
    get_title_predictions,
)


def render() -> None:
    data = get_title_predictions()
    theme.page_header(
        "Season overview",
        "Monte Carlo title odds from a blend of Elo, Poisson and XGBoost models, next to what the press is saying about each club.",
        [theme.chip("Season", "2026-27")],
    )

    if data is None:
        theme.api_error()
        return
    if data.get("status") != "ready" or not data.get("predictions"):
        theme.empty_state("No predictions yet", data.get("message") or "Run the pipeline to generate the first forecast.")
        return

    preds = pd.DataFrame(data["predictions"]).sort_values("win_probability", ascending=False).reset_index(drop=True)
    colors = theme.team_colors(preds["team"].tolist())
    matchweek = int(data["matchweek"])
    summaries = get_matchweek_summaries(matchweek)
    total_articles = sum(s["summary"]["total_articles"] for s in summaries.values())
    leader, runner_up = preds.iloc[0], preds.iloc[1]

    top5 = preds.head(5)
    theme.contender_band(
        [(r["team"], float(r["win_probability"]), theme.color_for(r["team"], colors)) for _, r in top5.iterrows()],
        max_value=float(top5["win_probability"].max()),
    )

    theme.stat_strip(
        [
            ("Title favourite", leader["team"], f"{leader['win_probability']:.1%} to win the league"),
            ("Lead over " + runner_up["team"], f"{(leader['win_probability'] - runner_up['win_probability']) * 100:.1f} pp", "gap in title probability"),
            ("Matchweeks played", theme.counted(matchweek, " of 38"), f"model {data.get('model_version', '')}"),
            ("Articles analysed", theme.counted(total_articles), "scored for sentiment this season"),
        ]
    )

    left, right = st.columns([5, 7], gap="medium")
    with left:
        with theme.panel("Where the title probability sits", "top 5 plus the rest"):
            theme.show(charts.title_donut(preds, colors, top=5, height=318), key="ov-donut")
    with right:
        with theme.panel("Title odds", f"after matchweek {matchweek}"):
            top = preds.head(8)
            theme.ranked_bars(
                [(r["team"], float(r["win_probability"]), theme.color_for(r["team"], colors)) for _, r in top.iterrows()],
                max_value=float(top["win_probability"].max()),
            )
            st.markdown(f'<div class="note">{len(preds) - len(top)} more clubs on the Title race page.</div>', unsafe_allow_html=True)

    left, right = st.columns([7, 5], gap="medium")
    with left:
        week_data = summaries.get(matchweek)
        with theme.panel(f"Press sentiment, matchweek {matchweek}", f"clubs with {charts.MIN_ARTICLES}+ articles"):
            fig = charts.sentiment_bars(pd.DataFrame(week_data["standings"]), height=560, colors=colors) if week_data else None
            if fig is None:
                theme.empty_state("Not enough coverage yet", "No club has enough articles this matchweek to say anything about sentiment.")
            else:
                theme.show(fig, key="ov-sent")
    with right:
        fixtures = get_fixture_forecasts()
        shown = fixtures.get("fixtures", []) if isinstance(fixtures, dict) and fixtures.get("status") == "ready" else []
        label = f"matchweek {fixtures['matchweek']}" if shown else ""
        with theme.panel("Next fixtures", label):
            if shown:
                st.markdown("".join(theme.fixture_row(f) for f in shown[:6]), unsafe_allow_html=True)
                st.markdown(theme.FIXTURE_LEGEND, unsafe_allow_html=True)
            else:
                theme.empty_state("No fixture forecasts yet", "They are stored each time the matchweek pipeline runs.")

    with theme.panel("The twenty clubs", "ordered by title probability; hover for the odds"):
        theme.club_wall([(r["team"], f"{r['team']}: {r['win_probability']:.1%} to win the league") for _, r in preds.iterrows()])

    st.markdown(
        f'<div class="note">Last refreshed {datetime.now().strftime("%d %b %Y, %H:%M")} · data is cached for 30 seconds.</div>',
        unsafe_allow_html=True,
    )
