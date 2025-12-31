"""
PLanalyst — Streamlit Page: Team Detail

One club: its record, how its points built up, what it scored and conceded, how the press
covered it, and what the model thinks of its season.
"""

import pandas as pd
import streamlit as st

from streamlit_app import charts, theme
from streamlit_app.utils import (
    TEAMS,
    get_team_performance,
    get_team_sentiment,
    get_title_predictions,
)


def render() -> None:
    theme.page_header("Team detail", "Results, form and press coverage for one club, with the model's view of its season.")

    follow = theme.followed()
    team = st.selectbox(
        "Club shown", TEAMS, index=TEAMS.index(follow) if follow else 1,
        help="Starts on the club you follow. Changing it here only changes this page, not who you follow.",
    )
    if not team:
        return

    sentiment_data = get_team_sentiment(team)
    performance_data = get_team_performance(team)
    if sentiment_data is None or performance_data is None:
        theme.api_error()
        return
    if "error" in sentiment_data or "error" in performance_data:
        theme.empty_state(f"No data for {team} yet", "This club has no scored matches or articles so far.")
        return

    perf = pd.DataFrame(performance_data.get("performance", []))
    sent = pd.DataFrame(sentiment_data.get("sentiment_trend", []))
    if perf.empty:
        theme.empty_state(f"{team} hasn't played yet", "Results appear here after the first matchweek.")
        return

    predictions = pd.DataFrame((get_title_predictions() or {}).get("predictions", []))
    ranked = predictions.sort_values("win_probability", ascending=False)["team"].tolist() if not predictions.empty else []
    colors = theme.team_colors(ranked)
    color = colors.get(team, "#9ec5f4")
    mine = predictions[predictions["team"] == team].iloc[0] if not predictions.empty and (predictions["team"] == team).any() else None

    latest = perf.iloc[-1]
    wins, draws, losses = (int((perf["result"] == r).sum()) for r in ("W", "D", "L"))
    gf, ga = int(perf["goals_for"].sum()), int(perf["goals_against"].sum())

    theme.team_hero(
        team,
        [
            theme.chip("Played", str(len(perf))),
            theme.chip("Form", " ".join(perf["result"].tail(5))),
            *([theme.chip("Title", f"{mine['win_probability']:.1%}")] if mine is not None else []),
        ],
    )

    theme.stat_strip(
        [
            ("Points", theme.counted(int(latest["cumulative_points"])), f"after {len(perf)} matches"),
            ("Record", f"{wins}-{draws}-{losses}", "wins, draws, losses"),
            ("Goals", f"{gf}:{ga}", f"goal difference {int(latest['cumulative_gd']):+d}"),
            ("Title chance", "n/a" if mine is None else f"{mine['win_probability']:.1%}",
             "" if mine is None else f"top 4 {mine['top4_probability']:.0%} · relegation {mine['relegation_probability']:.0%}"),
        ]
    )

    left, right = st.columns([4, 8], gap="medium")
    with left:
        with theme.panel("Form", "oldest → newest"):
            theme.form_strip(perf["result"].tolist())
            theme.show(charts.result_donut(perf, height=240), key="td-donut")
    with right:
        with theme.panel("Points accumulation"):
            theme.show(charts.points_line(perf, color, height=326), key="td-points")

    left, right = st.columns(2, gap="medium")
    with left:
        with theme.panel("Goals for and against", "per match"):
            theme.show(charts.goals_chart(perf, color), key="td-goals")
    with right:
        with theme.panel("Press sentiment", "hollow dot = under 8 articles"):
            if sent.empty:
                theme.empty_state("No coverage yet", f"No scored articles mention {team} so far.")
            else:
                theme.show(charts.sentiment_trend(sent, color), key="td-sent")

    with theme.panel("Did coverage follow the result?", "needs 3+ matchweeks with 8+ articles"):
        fig = charts.sentiment_vs_goal_diff(perf, sent) if not sent.empty else None
        if fig is None:
            theme.empty_state("Not enough coverage to compare", "Once three matchweeks have enough articles, this plots sentiment against each match's goal difference.")
        else:
            theme.show(fig, key="td-corr")
