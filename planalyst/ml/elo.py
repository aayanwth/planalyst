"""
PLanalyst — Elo ratings with home advantage, season-to-season regression and promoted teams.

One implementation feeds training features, live scoring, the evaluation harness and the
backtest, so they can never disagree about a team's rating.

Rules
  * Every team starts at DEFAULT_ELO in the first season present in the data.
  * A team first seen in a LATER season (a promoted side) starts at `new_team_elo`.
  * At the start of each new season every rating is pulled `season_regression` of the way
    back to DEFAULT_ELO (squads change over the summer).
  * The expected score includes `home_advantage` Elo points for the home side. The rating a
    team carries (and that is used as a model feature) excludes it.
  * Updates are scaled by log(goal difference + 1) so bigger wins move ratings more.

The three tunable values below were selected on validation seasons that do not overlap the
evaluation seasons; `python -m planalyst.ml.tune` reproduces the selection.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DEFAULT_ELO = 1500.0
K_FACTOR = 32.0


@dataclass(frozen=True)
class EloParams:
    k: float = K_FACTOR
    home_advantage: float = 0.0
    season_regression: float = 0.0
    new_team_elo: float = DEFAULT_ELO
    draw_prob: float = 0.26


# Selected on validation seasons 2018-19 by `elo_validation_table` in tune.py (480 combinations;
# the optimum is interior for home advantage and draw rate). Season regression came out at 0:
# with K = 32 ratings re-adapt quickly, and pulling them to the mean made forecasts worse.
# The promoted-team start (1450) is a sensible prior but its effect is within noise.
DEFAULT_PARAMS = EloParams(
    home_advantage=90.0, season_regression=0.0, new_team_elo=1450.0, draw_prob=0.22
)


def expected_home_score(
    home_elo: float, away_elo: float, home_advantage: float = 0.0
) -> float:
    """Expected score (win = 1, draw = 0.5) of the home side."""
    return 1 / (1 + 10 ** ((away_elo - (home_elo + home_advantage)) / 400))


def outcome_probs(
    home_elo: float, away_elo: float, params: EloParams | None = None
) -> np.ndarray:
    """[P(home win), P(draw), P(away win)] from ratings and a fixed draw rate."""
    p = params or DEFAULT_PARAMS
    exp_home = expected_home_score(home_elo, away_elo, p.home_advantage)
    return np.array(
        [(1 - p.draw_prob) * exp_home, p.draw_prob, (1 - p.draw_prob) * (1 - exp_home)]
    )


def outcome_probs_array(
    home_elo: np.ndarray, away_elo: np.ndarray, params: EloParams | None = None
) -> np.ndarray:
    """Vectorised `outcome_probs`: (n, 3) array of [P(home), P(draw), P(away)]."""
    p = params or DEFAULT_PARAMS
    h, a = np.asarray(home_elo, dtype=float), np.asarray(away_elo, dtype=float)
    exp_home = 1 / (1 + 10 ** ((a - (h + p.home_advantage)) / 400))
    return np.column_stack(
        [(1 - p.draw_prob) * exp_home, np.full(len(h), p.draw_prob), (1 - p.draw_prob) * (1 - exp_home)]
    )


def run_elo(
    matches: pd.DataFrame, params: EloParams | None = None
) -> tuple[dict[str, float], pd.DataFrame]:
    """
    Replay `matches` (needs season, matchday, home_team_name, away_team_name, score_home,
    score_away) in time order.

    Returns (final ratings, pre-match table). The table has one row per match with the
    home/away ratings as they stood BEFORE that match was played.
    """
    p = params or DEFAULT_PARAMS
    ordered = matches.sort_values(["season", "matchday"], kind="stable")

    ratings: dict[str, float] = {}
    pre_rows: list[tuple] = []
    current_season = None
    first_season = None

    for row in ordered.itertuples(index=False):
        if row.season != current_season:
            if current_season is None:
                first_season = row.season
            elif p.season_regression:
                for team in ratings:
                    ratings[team] = DEFAULT_ELO + (1 - p.season_regression) * (
                        ratings[team] - DEFAULT_ELO
                    )
            current_season = row.season

        home, away = row.home_team_name, row.away_team_name
        for team in (home, away):
            if team not in ratings:
                ratings[team] = DEFAULT_ELO if row.season == first_season else p.new_team_elo

        h, a = ratings[home], ratings[away]
        pre_rows.append((row.season, row.matchday, home, away, h, a))

        expected = expected_home_score(h, a, p.home_advantage)
        if row.score_home > row.score_away:
            actual = 1.0
        elif row.score_home < row.score_away:
            actual = 0.0
        else:
            actual = 0.5
        margin = np.log(max(abs(row.score_home - row.score_away), 1) + 1)
        delta = p.k * margin * (actual - expected)
        ratings[home] = h + delta
        ratings[away] = a - delta

    pre = pd.DataFrame(
        pre_rows, columns=["season", "matchday", "home", "away", "home_elo", "away_elo"]
    )
    return ratings, pre


def pre_match_long(pre: pd.DataFrame) -> pd.DataFrame:
    """Pre-match table -> one row per (season, matchday, team) with own and opponent rating."""
    home = pre.rename(columns={"home": "team", "home_elo": "elo_rating", "away_elo": "opp_elo"})
    away = pre.rename(columns={"away": "team", "away_elo": "elo_rating", "home_elo": "opp_elo"})
    cols = ["season", "matchday", "team", "elo_rating", "opp_elo"]
    return pd.concat([home[cols], away[cols]], ignore_index=True)
