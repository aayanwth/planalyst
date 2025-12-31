"""Shared fixtures: a small synthetic league with known team strengths."""

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

TEAM_STRENGTH = {
    "Alpha": 1.0,
    "Bravo": 0.6,
    "Charlie": 0.2,
    "Delta": -0.2,
    "Echo": -0.6,
    "Foxtrot": -1.0,
}


def round_robin(teams: list[str]) -> list[list[tuple[str, str]]]:
    """Circle-method double round robin: every team plays exactly once per round."""
    n = len(teams)
    rotation = teams[:]
    first_leg = []
    for _ in range(n - 1):
        pairs = [(rotation[i], rotation[n - 1 - i]) for i in range(n // 2)]
        first_leg.append(pairs)
        rotation = [rotation[0]] + [rotation[-1]] + rotation[1:-1]
    second_leg = [[(a, h) for h, a in rnd] for rnd in first_leg]
    return first_leg + second_leg


def make_league(seasons=(2018, 2019, 2020, 2021, 2022, 2023), seed: int = 0) -> pd.DataFrame:
    """Matches in the `training.historical_matches` layout; goals ~ Poisson driven by strength."""
    rng = np.random.default_rng(seed)
    rows, match_id = [], 0
    for season in seasons:
        for matchday, rnd in enumerate(round_robin(list(TEAM_STRENGTH)), start=1):
            for home, away in rnd:
                diff = TEAM_STRENGTH[home] - TEAM_STRENGTH[away]
                sh = int(rng.poisson(np.exp(0.25 + 0.35 * diff)))
                sa = int(rng.poisson(np.exp(0.0 - 0.35 * diff)))
                match_id += 1
                rows.append(
                    {
                        "id": match_id,
                        "matchday": matchday,
                        "season": season,
                        "season_label": f"{season}-{season + 1}",
                        "home_team_name": home,
                        "away_team_name": away,
                        "score_home": sh,
                        "score_away": sa,
                        "score_winner": (
                            "HOME_TEAM" if sh > sa else "AWAY_TEAM" if sh < sa else "DRAW"
                        ),
                    }
                )
    return pd.DataFrame(rows)


@pytest.fixture(scope="session")
def league() -> pd.DataFrame:
    return make_league()


@pytest.fixture()
def sqlite_engine():
    """In-memory SQLite with `gold` and `public_gold` attached, standing in for Postgres schemas."""
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def attach_schemas(dbapi_conn, _):
        for schema in ("public_gold", "gold", "bronze", "training"):
            dbapi_conn.execute(f"ATTACH DATABASE ':memory:' AS {schema}")

    return engine
