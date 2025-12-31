"""
PLanalyst — Streamlit Page: Fixtures & Accuracy

Forecasts for each fixture of a matchweek, and how the forecasts stored before kick-off have
scored against real results this season (compared with a naive historical-frequency baseline).
"""

import pandas as pd
import streamlit as st

from streamlit_app import charts, theme
from streamlit_app.utils import get_fixture_forecasts, get_live_accuracy

MIN_MATCHES_FOR_CONFIDENCE = 100


def render_fixtures() -> None:
    data = get_fixture_forecasts()
    if data is None:
        theme.api_error()
        return
    if data.get("status") != "ready":
        theme.empty_state("No fixture forecasts yet", "They are stored each time the matchweek pipeline runs.")
        return

    default_week = int(data["matchweek"])
    week = st.number_input("Matchweek", min_value=1, max_value=38, value=default_week, step=1)
    shown = data if week == default_week else get_fixture_forecasts(int(week))
    if not shown or not shown.get("fixtures"):
        theme.empty_state(f"No forecasts for matchweek {week}", "Forecasts are only stored for matchweeks the pipeline has run.")
        return

    fixtures = shown["fixtures"]
    home = sum(f["p_home"] for f in fixtures) / len(fixtures)
    draw = sum(f["p_draw"] for f in fixtures) / len(fixtures)
    away = sum(f["p_away"] for f in fixtures) / len(fixtures)
    surest = max(fixtures, key=lambda f: max(f["p_home"], f["p_draw"], f["p_away"]))
    pick = max(("home", surest["p_home"]), ("draw", surest["p_draw"]), ("away", surest["p_away"]), key=lambda t: t[1])
    winner = surest["home_team"] if pick[0] == "home" else (surest["away_team"] if pick[0] == "away" else "a draw")

    theme.stat_strip(
        [
            ("Fixtures", theme.counted(len(fixtures)), f"matchweek {week}"),
            ("Expected home wins", f"{home * len(fixtures):.1f}", f"{home:.0%} average probability"),
            ("Most confident call", f"{pick[1]:.0%}", f"{winner} ({surest['home_team']} v {surest['away_team']})"),
        ]
    )

    left, right = st.columns([8, 4], gap="medium")
    with left:
        with theme.panel("Fixture forecasts", f"matchweek {week}"):
            st.markdown("".join(theme.fixture_row(x) for x in fixtures), unsafe_allow_html=True)
            st.markdown(theme.FIXTURE_LEGEND, unsafe_allow_html=True)
    with right:
        with theme.panel("Matchweek outcome mix", "average probability", stretch=False):
            fig = theme.donut(
                ["Home win", "Draw", "Away win"], [home, draw, away], [theme.HOME, theme.DRAW_C, theme.AWAY],
                center_text=f"{home:.0%}", center_sub="home win", height=320,
            )
            theme.show(fig, key="fx-donut")
        st.markdown(
            '<div class="note">Probabilities blend an XGBoost model, Elo ratings and a Poisson goals model. '
            "A forecast is refreshed until kick-off and then frozen.</div>",
            unsafe_allow_html=True,
        )


def render_accuracy() -> None:
    acc = get_live_accuracy()
    if acc is None:
        theme.api_error()
        return
    n = acc.get("matches_scored", 0)
    with theme.panel("Live accuracy", "forecasts frozen before kick-off, scored on real results"):
        if not n:
            theme.empty_state(
                "No forecast has been scored yet",
                "Forecasts are stored before each match, so this is an honest out-of-sample record. "
                "It starts filling in after the first stored matchweek has been played.",
            )
            return
        model, baseline = acc["model"], acc.get("baseline")
        delta = "" if not baseline else f"{model['log_loss'] - baseline['log_loss']:+.3f} vs baseline"
        theme.stat_strip(
            [
                ("Matches scored", theme.counted(int(n)), "out of sample"),
                ("Log loss", f"{model['log_loss']:.3f}", delta or "lower is better"),
                ("Accuracy", f"{model['accuracy']:.1%}", "share of results called correctly"),
            ]
        )
        if n < MIN_MATCHES_FOR_CONFIDENCE:
            st.info(
                f"Only {n} matches scored so far. Single-season football results are noisy; "
                "differences this small are not evidence either way."
            )
        weeks = pd.DataFrame(acc["by_matchweek"])
        if not weeks.empty:
            theme.show(charts.accuracy_chart(weeks, baseline["log_loss"] if baseline else None), key="fx-acc")
            st.dataframe(
                weeks.rename(columns={"matchweek": "Matchweek", "n": "Matches", "log_loss": "Log loss", "rps": "RPS", "accuracy": "Accuracy"})
                [["Matchweek", "Matches", "Log loss", "RPS", "Accuracy"]],
                hide_index=True, width="stretch",
            )


def render() -> None:
    theme.page_header(
        "Fixtures & accuracy",
        "What the model expects in each match, and how its earlier forecasts have held up.",
    )
    render_fixtures()
    st.markdown('<div style="height:20px"></div>', unsafe_allow_html=True)
    render_accuracy()
