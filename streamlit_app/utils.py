"""
PLanalyst — Streamlit Dashboard: Utility functions

Helper functions for calling the FastAPI backend.
"""

import os
import re

import pandas as pd
import requests
import streamlit as st

API_BASE_URL = os.getenv("PLANALYST_API_URL", "http://localhost:8000")

TEAMS = [
    "AFC Bournemouth", "Arsenal", "Aston Villa", "Brentford",
    "Brighton & Hove Albion", "Chelsea", "Coventry City", "Crystal Palace",
    "Everton", "Fulham", "Hull City", "Ipswich Town", "Leeds United",
    "Liverpool", "Manchester City", "Manchester United", "Newcastle United",
    "Nottingham Forest", "Sunderland", "Tottenham Hotspur",
]
NO_FOLLOW = "— none —"


@st.cache_data(ttl=30, show_spinner=False)
def api_get(endpoint: str) -> dict | list | None:
    """Make a GET request to the FastAPI backend (cached for 30 s so page switches stay snappy)."""
    try:
        response = requests.get(f"{API_BASE_URL}{endpoint}", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        return None
    except requests.exceptions.HTTPError as e:
        return {"error": str(e)}


def api_is_up() -> bool:
    return isinstance(api_get("/health"), dict)


def latest_matchweek(default: int = 1) -> int:
    """The most recent matchweek the model has scored (falls back to `default`)."""
    data = get_title_predictions()
    if isinstance(data, dict) and data.get("matchweek"):
        return int(data["matchweek"])
    return default


def get_matchweek_summaries(last: int) -> dict[int, dict]:
    """Summaries for matchweeks 1..last that have data, keyed by matchweek."""
    out: dict[int, dict] = {}
    for week in range(1, last + 1):
        data = get_matchweek_summary(week)
        if isinstance(data, dict) and "error" not in data:
            out[week] = data
    return out


def get_clubs() -> dict[str, dict]:
    """team name -> {tla, short, crest} for every club, from the latest matchweek the API can summarise.

    Crest links come from the football-data.org feed the pipeline already ingests (dim_team.crest_url).
    """
    for week in range(latest_matchweek(), 0, -1):
        data = get_matchweek_summary(week)
        if isinstance(data, dict) and data.get("standings"):
            return {
                row["team"]: {"tla": row.get("tla") or row["team"][:3].upper(), "short": row.get("short_name") or row["team"],
                              "crest": row.get("crest_url") or ""}
                for row in data["standings"]
            }
    return {}


def get_team_sentiment(team_name: str) -> dict | None:
    return api_get(f"/team/{team_name}/sentiment")


def get_team_performance(team_name: str) -> dict | None:
    return api_get(f"/team/{team_name}/performance")


def get_matchweek_summary(matchweek: int) -> dict | None:
    return api_get(f"/matchweek/{matchweek}/summary")


def get_title_predictions() -> dict | None:
    return api_get("/predictions/title")


def get_prediction_history() -> dict | None:
    return api_get("/predictions/history")


def get_fixture_forecasts(matchweek: int | None = None) -> dict | None:
    endpoint = "/predictions/fixtures"
    return api_get(endpoint if matchweek is None else f"{endpoint}?matchweek={matchweek}")


def get_live_accuracy() -> dict | None:
    return api_get("/predictions/accuracy")


IMAGE_LINE = re.compile(r"^!\[(?P<alt>[^\]]*)\]\((?P<path>[^)]+)\)\s*$")


def split_report(text: str) -> list[tuple[str, str]]:
    """Split markdown into ("markdown", chunk) and ("image", relative_path) blocks."""
    blocks: list[tuple[str, str]] = []
    chunk: list[str] = []
    for line in text.splitlines():
        match = IMAGE_LINE.match(line.strip())
        if match:
            if chunk:
                blocks.append(("markdown", "\n".join(chunk)))
                chunk = []
            blocks.append(("image", match.group("path")))
        else:
            chunk.append(line)
    if chunk:
        blocks.append(("markdown", "\n".join(chunk)))
    return blocks


def parse_md_tables(text: str) -> list[tuple[str, pd.DataFrame]]:
    """Extract every markdown pipe table as (nearest preceding text, DataFrame of strings)."""
    tables: list[tuple[str, pd.DataFrame]] = []
    lines = text.splitlines()
    i, last_text = 0, ""
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and i + 1 < len(lines) and set(lines[i + 1].replace("|", "").strip()) <= set("-: "):
            header = [c.strip() for c in line.strip("|").split("|")]
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            tables.append((last_text, pd.DataFrame(rows, columns=header)))
            continue
        if line and not line.startswith("!["):
            last_text = line
        i += 1
    return tables


def to_numeric(df: pd.DataFrame, skip: tuple[str, ...] = ()) -> pd.DataFrame:
    """Convert every column that parses as numbers (except `skip`) to float."""
    out = df.copy()
    for column in out.columns:
        if column not in skip:
            out[column] = pd.to_numeric(out[column], errors="coerce").where(lambda s: s.notna(), out[column])
    return out
