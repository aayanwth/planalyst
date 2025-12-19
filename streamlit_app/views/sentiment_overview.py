"""
PLanalyst — Streamlit Page: Matchweek Sentiment Overview

Shows sentiment vs points scatter plot, standings table, and
most positive/negative teams for the selected matchweek.
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from streamlit_app.utils import get_matchweek_summary


def render():
    st.markdown("# 🏟️ Matchweek Overview")

    # Matchweek selector
    matchweek = st.slider("Select Matchweek", min_value=1, max_value=38, value=1)

    data = get_matchweek_summary(matchweek)

    if data is None:
        st.error("Cannot connect to the API. Make sure FastAPI is running on port 8000.")
        return

    if "error" in data:
        st.warning(f"No data for Matchweek {matchweek} yet.")
        return

    # ── Summary metrics ──────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Goals", data["summary"]["total_goals"])
    with col2:
        st.metric("Avg Sentiment", f"{data['summary']['avg_sentiment']:.3f}")
    with col3:
        st.metric("Total Articles", data["summary"]["total_articles"])

    st.divider()

    # ── Sentiment vs Points Scatter ──────────────────────────────────────
    standings = pd.DataFrame(data["standings"])
    if data["summary"]["total_articles"] == 0:
        st.info("No news articles are attributed to this matchweek yet, so sentiment shows as neutral (0).")
    # Marker size must be > 0 or teams with no articles vanish from the scatter
    standings["marker_size"] = standings["article_count"] + 1

    if not standings.empty:
        col_left, col_right = st.columns([3, 2])

        with col_left:
            has_sentiment = standings["avg_sentiment"].nunique() > 1
            if has_sentiment:
                st.markdown("### Sentiment vs Points")
                # Points are only 0/1/3, so spread teams vertically to keep labels readable
                standings["points_jitter"] = standings["points"] + (
                    (standings.index % 7) - 3
                ) * 0.08
                fig = px.scatter(
                    standings,
                    x="avg_sentiment",
                    y="points_jitter",
                    text="tla",
                    size="marker_size",
                    size_max=30,
                    color="points",
                    color_continuous_scale=["#ef4444", "#f59e0b", "#22c55e"],
                    hover_data=["team", "result", "goals_for", "goals_against", "article_count"],
                )
                fig.update_traces(textposition="top center", textfont_size=10)
                fig.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    xaxis_title="Average Sentiment Score",
                    yaxis_title="Points",
                    height=450,
                    font=dict(family="Inter"),
                )
            else:
                # No sentiment signal this matchweek: show results instead of a flat line
                st.markdown("### Points This Matchweek")
                ordered = standings.sort_values(["points", "goals_for"], ascending=True)
                colors = {"W": "#22c55e", "D": "#f59e0b", "L": "#ef4444"}
                fig = go.Figure(go.Bar(
                    x=ordered["points"],
                    y=ordered["team"],
                    orientation="h",
                    marker_color=ordered["result"].map(colors),
                    text=ordered["result"] + "  " + ordered["goals_for"].astype(str)
                         + "-" + ordered["goals_against"].astype(str),
                    textposition="inside",
                ))
                fig.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    xaxis_title="Points",
                    height=600,
                    font=dict(family="Inter"),
                    showlegend=False,
                )
            st.plotly_chart(fig, use_container_width=True)

        with col_right:
            st.markdown("### Most Positive Teams")
            for team_data in data.get("most_positive_teams", [])[:5]:
                sentiment_val = team_data["sentiment"]
                color = "🟢" if sentiment_val > 0 else ("🔴" if sentiment_val < 0 else "🟡")
                st.markdown(f"{color} **{team_data['team']}** — {sentiment_val:.3f} ({team_data['articles']} articles)")

            st.markdown("### Most Negative Teams")
            for team_data in data.get("most_negative_teams", [])[:5]:
                sentiment_val = team_data["sentiment"]
                color = "🔴" if sentiment_val < 0 else ("🟡" if sentiment_val == 0 else "🟢")
                st.markdown(f"{color} **{team_data['team']}** — {sentiment_val:.3f} ({team_data['articles']} articles)")

    # ── League Table ─────────────────────────────────────────────────────
    st.divider()
    st.markdown("### League Standings")

    if not standings.empty:
        display_df = standings[["team", "result", "goals_for", "goals_against",
                                "points", "cumulative_points", "cumulative_gd",
                                "avg_sentiment", "article_count"]].copy()
        display_df.columns = ["Team", "Result", "GF", "GA", "Pts", "Total Pts", "GD",
                              "Sentiment", "Articles"]
        display_df.index = range(1, len(display_df) + 1)
        display_df.index.name = "#"
        st.dataframe(display_df, use_container_width=True, height=600)
