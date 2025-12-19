"""
PLanalyst — FastAPI Application

Serves Gold layer data via REST endpoints for the Streamlit dashboard.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from planalyst.api.routers import team, matchweek, predictions

app = FastAPI(
    title="PLanalyst API",
    description="Premier League News Sentiment vs Match Outcome API",
    version="0.1.0",
)

# CORS for Streamlit
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(team.router, prefix="/team", tags=["Team"])
app.include_router(matchweek.router, prefix="/matchweek", tags=["Matchweek"])
app.include_router(predictions.router, prefix="/predictions", tags=["Predictions"])


@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "project": "PLanalyst", "version": "0.1.0"}


@app.get("/health", tags=["Health"])
def health():
    return {"status": "healthy"}
