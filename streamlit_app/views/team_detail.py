"""
PLanalyst — Streamlit Page: Team Detail

Per-team sentiment trend line and performance timeline.
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from streamlit_app.utils import get_team_sentiment, get_team_performance


# Teams list for the dropdown
TEAMS = [
    "AFC Bournemouth", "Arsenal", "Aston Villa", "Brentford",
    "Brighton & Hove Albion", "Chelsea", "Coventry City", "Crystal Palace",
    "Everton", "Fulham", "Hull City", "Ipswich Town", "Leeds United",
    "Liverpool", "Manchester City", "Manchester United", "Newcastle United",
    "Nottingham Forest", "Sunderland", "Tottenham Hotspur",
]


def render():
    st.markdown("# 📊 Team Detail")

    team = st.selectbox("Select Team", TEAMS, index=1)  # Default: Arsenal

    if not team:
        return

    # Fetch data
    sentiment_data = get_team_sentiment(team)
    performance_data = get_team_performance(team)

    if sentiment_data is None or performance_data is None:
        st.error("Cannot connect to the API. Make sure FastAPI is running on port 8000.")
        return

    if "error" in sentiment_data or "error" in performance_data:
        st.warning(f"No data available for {team} yet.")
        return

    # ── Performance Summary ──────────────────────────────────────────────
    perf_list = performance_data.get("performance", [])
    if perf_list:
        latest = perf_list[-1]
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Points", latest["cumulative_points"])
        with col2:
            st.metric("Goal Difference", latest["cumulative_gd"])
        with col3:
            wins = sum(1 for p in perf_list if p["result"] == "W")
            st.metric("Wins", wins)
        with col4:
            losses = sum(1 for p in perf_list if p["result"] == "L")
            st.metric("Losses", losses)

    st.divider()

    # ── Dual axis chart: Sentiment + Points over matchweeks ──────────────
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("### Sentiment Trend")
        sent_list = sentiment_data.get("sentiment_trend", [])
        if sent_list:
            df_sent = pd.DataFrame(sent_list)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_sent["matchweek"],
                y=df_sent["avg_sentiment_score"],
                mode="lines+markers",
                name="Avg Sentiment",
                line=dict(color="#8b5cf6", width=3),
                marker=dict(size=8),
                fill="tozeroy",
                fillcolor="rgba(139, 92, 246, 0.1)",
            ))
            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis_title="Matchweek",
                yaxis_title="Sentiment Score",
                height=350,
                font=dict(family="Inter"),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No sentiment data available yet.")

    with col_right:
        st.markdown("### Points Accumulation")
        if perf_list:
            df_perf = pd.DataFrame(perf_list)
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_perf["matchweek"],
                y=df_perf["cumulative_points"],
                mode="lines+markers",
                name="Cumulative Points",
                line=dict(color="#22c55e", width=3),
                marker=dict(size=8),
                fill="tozeroy",
                fillcolor="rgba(34, 197, 94, 0.1)",
            ))
            fig.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis_title="Matchweek",
                yaxis_title="Cumulative Points",
                height=350,
                font=dict(family="Inter"),
            )
            st.plotly_chart(fig, use_container_width=True)

    # ── Results timeline ─────────────────────────────────────────────────
    st.divider()
    st.markdown("### Match Results")
    if perf_list:
        df_results = pd.DataFrame(perf_list)
        result_colors = {"W": "#22c55e", "D": "#f59e0b", "L": "#ef4444"}
        df_results["color"] = df_results["result"].map(result_colors)

        fig = go.Figure(data=[
            go.Bar(
                x=df_results["matchweek"],
                y=df_results["points"],
                marker_color=df_results["color"],
                text=df_results["result"],
                textposition="inside",
                hovertext=[
                    f"MW{r['matchweek']}: {r['goals_for']}-{r['goals_against']} ({r['result']})"
                    for _, r in df_results.iterrows()
                ],
            )
        ])
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis_title="Matchweek",
            yaxis_title="Points",
            height=300,
            font=dict(family="Inter"),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)
