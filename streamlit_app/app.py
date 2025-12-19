"""
PLanalyst — Streamlit Dashboard: Main App

Multi-page Streamlit app that visualizes Premier League sentiment
analysis and title predictions via the FastAPI backend.
"""

import sys
from pathlib import Path

import streamlit as st

# Make `streamlit_app` importable without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

st.set_page_config(
    page_title="PLanalyst - Premier League Sentiment & Predictions",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS for premium look ───────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    * { font-family: 'Inter', sans-serif; }

    .main { background: linear-gradient(135deg, #0a0e1a 0%, #1a1f35 50%, #0d1117 100%); }

    .stApp { background: linear-gradient(135deg, #0a0e1a 0%, #1a1f35 50%, #0d1117 100%); }

    h1, h2, h3 {
        background: linear-gradient(90deg, #6366f1, #8b5cf6, #a78bfa);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 700;
    }

    .metric-card {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 16px;
        padding: 20px;
        backdrop-filter: blur(10px);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }

    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(99, 102, 241, 0.15);
    }

    .team-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 6px 12px;
        background: rgba(99, 102, 241, 0.1);
        border-radius: 8px;
        font-weight: 500;
    }

    .positive { color: #22c55e; }
    .negative { color: #ef4444; }
    .neutral { color: #94a3b8; }

    .stMetric { background: rgba(255,255,255,0.03); border-radius: 12px; padding: 12px; }

    div[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #111827 0%, #1e1b4b 100%);
    }
</style>
""", unsafe_allow_html=True)


# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.markdown("# ⚽ PLanalyst")
st.sidebar.markdown("*Premier League Sentiment & Predictions*")
st.sidebar.divider()

page = st.sidebar.radio(
    "Navigate",
    ["🏟️ Matchweek Overview", "📊 Team Detail", "🏆 Title Race"],
    index=0,
)

st.sidebar.divider()
st.sidebar.markdown("---")
st.sidebar.caption("Data: football-data.org + BBC Sport RSS")
st.sidebar.caption("NLP: CardiffNLP twitter-roberta")
st.sidebar.caption("Season: 2026-2027")


# ── Page Routing ──────────────────────────────────────────────────────────────
if page == "🏟️ Matchweek Overview":
    from streamlit_app.views.sentiment_overview import render
    render()
elif page == "📊 Team Detail":
    from streamlit_app.views.team_detail import render
    render()
elif page == "🏆 Title Race":
    from streamlit_app.views.title_race import render
    render()
