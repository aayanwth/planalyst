"""
PLanalyst — Offline historical match loader (for evaluation and CI-free reproduction).

The production training set comes from football-data.org via dlt into Postgres
(`training.historical_matches`). The evaluation scripts need the same match-level
shape without a database or an API key, so this module reads the free per-season
results CSVs published by football-data.co.uk and returns a frame with the same
columns as that table.

Only result columns are read (date, teams, full-time score). The bookmaker-odds
columns in those files are deliberately ignored: odds are out of scope for this project.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import requests

from planalyst.config import PROJECT_ROOT

CACHE_DIR = PROJECT_ROOT / "data" / "football_data_uk"
BASE_URL = "https://www.football-data.co.uk/mmz4281/{code}/E0.csv"
RESULT_COLUMNS = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"]


# football-data.co.uk spells clubs differently from football-data.org. The live pipeline, the
# team-name seed and the Elo lookup all use the API spelling, so CSV rows are renamed to match.
API_TEAM_NAMES = {
    "Arsenal": "Arsenal FC",
    "Aston Villa": "Aston Villa FC",
    "Bournemouth": "AFC Bournemouth",
    "Brentford": "Brentford FC",
    "Brighton": "Brighton & Hove Albion FC",
    "Burnley": "Burnley FC",
    "Cardiff": "Cardiff City FC",
    "Chelsea": "Chelsea FC",
    "Crystal Palace": "Crystal Palace FC",
    "Everton": "Everton FC",
    "Fulham": "Fulham FC",
    "Huddersfield": "Huddersfield Town AFC",
    "Hull": "Hull City AFC",
    "Ipswich": "Ipswich Town FC",
    "Leeds": "Leeds United FC",
    "Leicester": "Leicester City FC",
    "Liverpool": "Liverpool FC",
    "Luton": "Luton Town FC",
    "Man City": "Manchester City FC",
    "Man United": "Manchester United FC",
    "Middlesbrough": "Middlesbrough FC",
    "Newcastle": "Newcastle United FC",
    "Norwich": "Norwich City FC",
    "Nott'm Forest": "Nottingham Forest FC",
    "Sheffield United": "Sheffield United FC",
    "Southampton": "Southampton FC",
    "Stoke": "Stoke City FC",
    "Sunderland": "Sunderland AFC",
    "Swansea": "Swansea City AFC",
    "Tottenham": "Tottenham Hotspur FC",
    "Watford": "Watford FC",
    "West Brom": "West Bromwich Albion FC",
    "West Ham": "West Ham United FC",
    "Wolves": "Wolverhampton Wanderers FC",
}


def to_api_names(df: pd.DataFrame) -> pd.DataFrame:
    """Rename home/away teams to football-data.org spelling; unknown clubs raise, never pass silently."""
    names = set(df["home_team_name"]) | set(df["away_team_name"])
    unknown = sorted(names - set(API_TEAM_NAMES))
    if unknown:
        raise ValueError(f"No API spelling for CSV teams: {unknown}")
    out = df.copy()
    out["home_team_name"] = out["home_team_name"].map(API_TEAM_NAMES)
    out["away_team_name"] = out["away_team_name"].map(API_TEAM_NAMES)
    return out


def season_code(season: int) -> str:
    """2015 -> '1516' (the site's directory naming)."""
    return f"{season % 100:02d}{(season + 1) % 100:02d}"


def download_season(season: int, cache_dir: Path = CACHE_DIR) -> Path:
    """Fetch one season's CSV into the cache (no-op if already cached)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"E0_{season_code(season)}.csv"
    if not path.exists():
        resp = requests.get(BASE_URL.format(code=season_code(season)), timeout=30)
        resp.raise_for_status()
        path.write_bytes(resp.content)
    return path


def assign_matchdays(df: pd.DataFrame) -> pd.Series:
    """
    Derive a round number for each match of ONE season, in date order.

    The CSVs carry no matchweek. A match's round is one more than the larger number of games
    its two teams have already played, so every team plays at most once per round and rounds
    stay chronological even when fixtures are postponed and replayed.
    """
    played: dict[str, int] = {}
    rounds = pd.Series(0, index=df.index, dtype="int64")
    for idx, row in df.sort_values("utc_date", kind="stable").iterrows():
        rnd = max(played.get(row["home_team_name"], 0), played.get(row["away_team_name"], 0)) + 1
        played[row["home_team_name"]] = rnd
        played[row["away_team_name"]] = rnd
        rounds.loc[idx] = rnd
    return rounds


def parse_season_csv(raw: bytes | str, season: int) -> pd.DataFrame:
    """Parse one season's CSV into the `training.historical_matches` column layout."""
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    csv = pd.read_csv(io.StringIO(text), usecols=lambda c: c in RESULT_COLUMNS)
    csv = csv.dropna(subset=["HomeTeam", "AwayTeam", "FTHG", "FTAG"])

    df = pd.DataFrame(
        {
            "utc_date": pd.to_datetime(csv["Date"], dayfirst=True, format="mixed"),
            "home_team_name": csv["HomeTeam"].str.strip(),
            "away_team_name": csv["AwayTeam"].str.strip(),
            "score_home": csv["FTHG"].astype(int),
            "score_away": csv["FTAG"].astype(int),
        }
    ).reset_index(drop=True)
    df["season"] = season
    df["season_label"] = f"{season}-{season + 1}"
    df["matchday"] = assign_matchdays(df)
    df["score_winner"] = "DRAW"
    df.loc[df["score_home"] > df["score_away"], "score_winner"] = "HOME_TEAM"
    df.loc[df["score_home"] < df["score_away"], "score_winner"] = "AWAY_TEAM"
    df["id"] = season * 1000 + df["utc_date"].rank(method="first").astype(int)
    return df


def load_matches(seasons: list[int], cache_dir: Path = CACHE_DIR) -> pd.DataFrame:
    """Load and concatenate finished matches for the given season start years."""
    frames = [parse_season_csv(download_season(s, cache_dir).read_bytes(), s) for s in seasons]
    return pd.concat(frames, ignore_index=True).sort_values(["season", "matchday", "id"])
