"""
PLanalyst — FastAPI Application

Serves Gold layer data via REST endpoints for the Streamlit dashboard.
"""

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from planalyst.api.database import engine
from planalyst.api.routers import matchweek, predictions, team
from planalyst.api.schemas import Health

VERSION = "0.2.0"

app = FastAPI(
    title="PLanalyst API",
    description="Premier League news sentiment, match results and title-race forecasts",
    version=VERSION,
)

# The dashboard calls this API server-side, so browsers normally never need CORS. Origins are
# an explicit allow-list (comma-separated PLANALYST_CORS_ORIGINS) rather than "*"; read-only.
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "PLANALYST_CORS_ORIGINS", "http://localhost:8501,http://127.0.0.1:8501"
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Register routers
app.include_router(team.router, prefix="/team", tags=["Team"])
app.include_router(matchweek.router, prefix="/matchweek", tags=["Matchweek"])
app.include_router(predictions.router, prefix="/predictions", tags=["Predictions"])


@app.get("/", tags=["Health"])
def root():
    return {"status": "ok", "project": "PLanalyst", "version": VERSION}


@app.get("/health", response_model=Health, tags=["Health"])
def health():
    """Liveness: the process is up. Does not touch the database."""
    return {"status": "healthy"}


@app.get("/ready", response_model=Health, tags=["Health"])
def ready():
    """Readiness: the database answers. Returns 503 otherwise."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"database unavailable: {type(exc).__name__}")
    return {"status": "ready"}
