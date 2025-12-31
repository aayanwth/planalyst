"""
PLanalyst — Streamlit Dashboard: Main App

Multi-page dashboard over the FastAPI serving layer: title odds, matchweek sentiment,
team detail, fixture forecasts and the model's own evaluation.
"""

import sys
from pathlib import Path

import streamlit as st

# Make `streamlit_app` importable without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from streamlit_app import theme  # noqa: E402
from streamlit_app.utils import NO_FOLLOW, TEAMS, api_is_up, get_clubs  # noqa: E402

st.set_page_config(
    page_title="PLanalyst · Premier League odds & sentiment",
    page_icon=":material/bar_chart:",
    layout="wide",
    initial_sidebar_state="auto",
)
theme.inject_css()
theme.set_clubs(get_clubs())  # crests and short names for every club, from the API


def overview():
    from streamlit_app.views.overview import render

    render()


def title_race():
    from streamlit_app.views.title_race import render

    render()


def matchweek():
    from streamlit_app.views.sentiment_overview import render

    render()


def team_detail():
    from streamlit_app.views.team_detail import render

    render()


def fixtures():
    from streamlit_app.views.fixtures import render

    render()


def model_evaluation():
    from streamlit_app.views.model_evaluation import render

    render()


STATIC = Path(__file__).resolve().parent / "static"
st.logo(str(STATIC / "logo.svg"), icon_image=str(STATIC / "mark.svg"), size="large")

navigation = st.navigation(
    [
        st.Page(overview, title="Overview", icon=":material/space_dashboard:", default=True),
        st.Page(title_race, title="Title race", icon=":material/emoji_events:", url_path="title-race"),
        st.Page(matchweek, title="Sentiment", icon=":material/forum:", url_path="matchweek"),
        st.Page(team_detail, title="Team detail", icon=":material/shield:", url_path="team"),
        st.Page(fixtures, title="Fixtures", icon=":material/sports_soccer:", url_path="fixtures"),
        st.Page(model_evaluation, title="Evaluation", icon=":material/science:", url_path="evaluation"),
    ]
)

with st.sidebar:
    st.markdown('<div class="side-label">Follow a club</div>', unsafe_allow_html=True)
    st.selectbox(
        "Follow a club", [NO_FOLLOW, *TEAMS], key="follow", label_visibility="collapsed",
        help="The club you follow burns brightest on every chart while the rest of the field recedes.",
    )
    if theme.followed():
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;padding:10px 4px 0">{theme.crest(theme.followed(), 36)}'
            f'<span style="color:var(--text);font-weight:600">{theme.followed()}</span></div>',
            unsafe_allow_html=True,
        )
    st.markdown(
        f'<div style="padding:18px 4px 0"><span class="chip">{theme.api_status_chip(api_is_up())}</span></div>',
        unsafe_allow_html=True,
    )
    st.caption("Results: football-data.org · News: Guardian, GDELT · Sentiment: CardiffNLP RoBERTa · Season 2026-27")

navigation.run()
