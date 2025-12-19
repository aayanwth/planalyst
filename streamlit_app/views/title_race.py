"""
PLanalyst — Streamlit Page: Title Race

Bar chart of predicted title-winning probability per team.
Shows which matchweek/model version the prediction is based on.
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from streamlit_app.utils import get_title_predictions


def render():
    st.markdown("# 🏆 Title Race Predictions")

    data = get_title_predictions()

    if data is None:
        st.error("Cannot connect to the API. Make sure FastAPI is running on port 8000.")
        return

    if data.get("status") == "pending":
        st.warning(data.get("message", "Predictions not yet available."))
        st.info(
            "To generate predictions, run the following steps:\n"
            "1. `python -m planalyst.pipelines.historical_matches` (ingest historical data)\n"
            "2. `python -m planalyst.ml.features` (build training features)\n"
            "3. `python -m planalyst.ml.train` (train the model)\n"
            "4. `python -m planalyst.ml.predict` (generate predictions)"
        )
        return

    predictions = data.get("predictions", [])
    matchweek = data.get("matchweek", 0)
    model_version = data.get("model_version", "xgb_v2")
    total_prob = data.get("total_probability", 0)

    if not predictions:
        st.warning("No predictions available yet.")
        return

    # ── Summary ──────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Based on Matchweek", matchweek)
    with col2:
        st.metric("Total Probability", f"{total_prob:.1%}")
    with col3:
        leader = predictions[0]["team"]
        leader_prob = predictions[0]["win_probability"]
        st.metric("Current Favorite", f"{leader} ({leader_prob:.1%})")

    st.divider()

    # ── Horizontal bar chart ─────────────────────────────────────────────
    st.markdown("### Title-Winning Probability")

    df = pd.DataFrame(predictions)
    df = df.sort_values("win_probability", ascending=True)

    fig = go.Figure(data=[
        go.Bar(
            x=df["win_probability"],
            y=df["team"],
            orientation="h",
            text=[f"{p:.1%}" for p in df["win_probability"]],
            textposition="outside",
            marker=dict(
                color=df["win_probability"],
                colorscale=[
                    [0, "#1e1b4b"],
                    [0.3, "#4338ca"],
                    [0.6, "#6366f1"],
                    [1, "#a78bfa"],
                ],
            ),
        )
    ])
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title="Win Probability",
        xaxis_tickformat=".0%",
        height=max(600, len(df) * 35),
        font=dict(family="Inter"),
        margin=dict(l=150),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Detailed table ───────────────────────────────────────────────────
    st.divider()
    st.markdown("### Detailed Predictions")

    display_df = pd.DataFrame(predictions)
    display_df["win_probability"] = display_df["win_probability"].apply(lambda x: f"{x:.1%}")
    display_df.columns = ["Team", "Win Probability", "Avg Final Points", "Avg Final Rank"]
    display_df.index = range(1, len(display_df) + 1)
    display_df.index.name = "Rank"
    st.dataframe(display_df, use_container_width=True)

    st.caption(
        f"Predictions based on Monte Carlo simulation (1000 iterations) using data through "
        f"Matchweek {matchweek}. Model version: {model_version}."
    )
