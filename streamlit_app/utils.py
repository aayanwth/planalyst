"""
PLanalyst — Streamlit Dashboard: Utility functions

Helper functions for calling the FastAPI backend.
"""

import os

import requests

API_BASE_URL = os.getenv("PLANALYST_API_URL", "http://localhost:8000")


def api_get(endpoint: str) -> dict | list | None:
    """Make a GET request to the FastAPI backend."""
    try:
        response = requests.get(f"{API_BASE_URL}{endpoint}", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        return None
    except requests.exceptions.HTTPError as e:
        return {"error": str(e)}


def get_team_sentiment(team_name: str) -> dict | None:
    return api_get(f"/team/{team_name}/sentiment")


def get_team_performance(team_name: str) -> dict | None:
    return api_get(f"/team/{team_name}/performance")


def get_matchweek_summary(matchweek: int) -> dict | None:
    return api_get(f"/matchweek/{matchweek}/summary")


def get_title_predictions() -> dict | None:
    return api_get("/predictions/title")
