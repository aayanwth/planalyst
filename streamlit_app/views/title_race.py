"""
PLanalyst — Streamlit Page: Title Race

Everything the simulation says about the final table: who wins, who finishes where, how wide
the uncertainty is, and how the odds have moved.
"""

import pandas as pd
import streamlit as st

from streamlit_app import charts, theme
from streamlit_app.utils import get_prediction_history, get_title_predictions

PROB_COLUMN = st.column_config.ProgressColumn(min_value=0.0, max_value=100.0, format="%.1f%%")


def render_history(colors: dict[str, str]) -> None:
    with theme.panel("How the odds have moved", "stored forecast per matchweek"):
        history = pd.DataFrame((get_prediction_history() or {}).get("history", []))
        fig = charts.odds_history(history, colors) if not history.empty else None
        if fig is None:
            theme.empty_state(
                "Waiting for a second forecast",
                "Each matchweek's forecast is stored, so this line chart fills in as the season goes on. It needs at least two scored matchweeks.",
            )
        else:
            theme.show(fig, key="tr-history")


def render() -> None:
    data = get_title_predictions()
    theme.page_header(
        "Title race",
        "Every remaining fixture is simulated 1,000 times from the current table. Each figure below is a share of those simulations.",
    )

    if data is None:
        theme.api_error()
        return
    if data.get("status") == "pending":
        theme.empty_state(
            "Predictions aren't ready",
            (data.get("message") or "")
            + " Run: historical_matches → ml.features → ml.train → ml.predict to generate them.",
        )
        return
    predictions = data.get("predictions", [])
    if not predictions:
        theme.empty_state("No predictions yet", "The model hasn't produced a forecast for this season.")
        return

    preds = pd.DataFrame(predictions).sort_values("win_probability", ascending=False).reset_index(drop=True)
    colors = theme.team_colors(preds["team"].tolist())
    matchweek = int(data.get("matchweek", 0))
    leader = preds.iloc[0]

    theme.stat_strip(
        [
            ("Favourite", leader["team"], f"{leader['win_probability']:.1%} title probability"),
            ("Expected points", f"{leader['avg_final_points']:.0f}", f"{leader['points_p10']:.0f}–{leader['points_p90']:.0f} likely range"),
            ("Top-4 certainty", theme.counted(int((preds['top4_probability'] > 0.9).sum()), " clubs"), "above 90% to finish top four"),
            ("Based on", f"Matchweek {matchweek}", f"model {data.get('model_version', 'unknown')}"),
        ]
    )

    left, right = st.columns([7, 5], gap="medium")
    with left:
        with theme.panel("Title probability", "top 10"):
            top = preds.head(10)
            theme.ranked_bars(
                [(r["team"], float(r["win_probability"]), theme.color_for(r["team"], colors)) for _, r in top.iterrows()],
                max_value=float(top["win_probability"].max()),
            )
    with right:
        with theme.panel("Share of the title"):
            theme.show(charts.title_donut(preds, colors, top=5, height=340), key="tr-donut")

    left, right = st.columns([6, 6], gap="medium")
    with left:
        with theme.panel("Expected final points", "dot = expected, bar = 10th–90th percentile"):
            theme.show(charts.points_range(preds, colors), key="tr-range")
    with right:
        with theme.panel("Where each club is likely to finish", "share of simulations"):
            theme.show(charts.probability_heatmap(preds), key="tr-heat")

    render_history(colors)

    with theme.panel("Full table"):
        table = preds.rename(
            columns={
                "team": "Team", "win_probability": "Title", "top4_probability": "Top 4", "relegation_probability": "Relegation",
                "avg_final_points": "Avg points", "points_p10": "Points p10", "points_p90": "Points p90", "avg_final_rank": "Avg rank",
            }
        )[["Team", "Title", "Top 4", "Relegation", "Avg points", "Points p10", "Points p90", "Avg rank"]]
        table.insert(0, "Crest", [theme.crest_url(t) for t in table["Team"]])
        for column in ("Title", "Top 4", "Relegation"):
            table[column] = table[column] * 100  # shown as 0-100 so the format matches the odds list
        st.dataframe(
            table, hide_index=True, width="stretch", height=420,
            column_config={"Crest": st.column_config.ImageColumn("", width="small"), "Title": PROB_COLUMN, "Top 4": PROB_COLUMN, "Relegation": PROB_COLUMN,
                           "Avg points": st.column_config.NumberColumn(format="%.1f"),
                           "Points p10": st.column_config.NumberColumn(format="%.0f"),
                           "Points p90": st.column_config.NumberColumn(format="%.0f"),
                           "Avg rank": st.column_config.NumberColumn(format="%.1f")},
        )
    st.markdown(
        '<div class="note">Points range is the 10th to 90th percentile of simulated final points. '
        'The title backtest behind this model rests on only six champions, so treat close calls as close.</div>',
        unsafe_allow_html=True,
    )
