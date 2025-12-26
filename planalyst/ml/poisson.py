"""
PLanalyst — Poisson goals model.

Goals for each side are modelled as independent Poisson counts whose log-mean is

    log E[goals] = intercept + attack(team) + defence(opponent) + home_effect * is_home

fitted as a ridge-regularised Poisson regression over all training matches (two rows per
match). The two expected-goal values are turned into a scoreline grid, which gives
[P(home win), P(draw), P(away win)] directly. Seasons can be down-weighted by age so recent
form counts for more. Clubs never seen in training get the league-average effect.

This is a candidate predictor evaluated in `evaluation.py` next to Elo and XGBoost; the
regularisation and decay were chosen on validation seasons (see `tune.py`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import poisson
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import PoissonRegressor
from sklearn.preprocessing import OneHotEncoder

MAX_GOALS = 10
# Selected on validation seasons 2018-19 by `poisson_validation_table` in tune.py. The optimum
# is a plateau (half-life 0.5-1.0 seasons, alpha 1e-4 to 1e-3 all within 0.001 log loss);
# these are from the middle of it. None as a half-life would weight every season equally.
DEFAULT_ALPHA = 0.001
DEFAULT_HALF_LIFE_SEASONS: float | None = 0.75


def _long_format(matches: pd.DataFrame) -> pd.DataFrame:
    """Two rows per match: (team, opponent, is_home, goals, season)."""
    home = pd.DataFrame(
        {
            "team": matches["home_team_name"].to_numpy(),
            "opp": matches["away_team_name"].to_numpy(),
            "is_home": 1,
            "goals": matches["score_home"].to_numpy(),
            "season": matches["season"].to_numpy(),
        }
    )
    away = pd.DataFrame(
        {
            "team": matches["away_team_name"].to_numpy(),
            "opp": matches["home_team_name"].to_numpy(),
            "is_home": 0,
            "goals": matches["score_away"].to_numpy(),
            "season": matches["season"].to_numpy(),
        }
    )
    return pd.concat([home, away], ignore_index=True)


def scoreline_outcome_probs(lam_home: np.ndarray, lam_away: np.ndarray) -> np.ndarray:
    """[P(home), P(draw), P(away)] per match from independent Poisson scorelines."""
    goals = np.arange(MAX_GOALS + 1)
    ph = poisson.pmf(goals[None, :], np.asarray(lam_home)[:, None])
    pa = poisson.pmf(goals[None, :], np.asarray(lam_away)[:, None])
    grid = ph[:, :, None] * pa[:, None, :]  # (n, home goals, away goals)
    home_win = np.triu(np.ones((MAX_GOALS + 1, MAX_GOALS + 1)), k=1).T  # home goals > away goals
    draw = np.eye(MAX_GOALS + 1)
    probs = np.stack(
        [
            (grid * home_win).sum(axis=(1, 2)),
            (grid * draw).sum(axis=(1, 2)),
            (grid * home_win.T).sum(axis=(1, 2)),
        ],
        axis=1,
    )
    return probs / probs.sum(axis=1, keepdims=True)  # renormalise the truncated tail


class PoissonGoalModel:
    def __init__(self, alpha: float = DEFAULT_ALPHA, half_life_seasons: float | None = DEFAULT_HALF_LIFE_SEASONS):
        self.alpha = alpha
        self.half_life_seasons = half_life_seasons
        self._encoder = ColumnTransformer(
            [("teams", OneHotEncoder(handle_unknown="ignore"), ["team", "opp"])],
            remainder="passthrough",
        )
        self._model = PoissonRegressor(alpha=alpha, max_iter=1000)

    def fit(self, matches: pd.DataFrame) -> PoissonGoalModel:
        long = _long_format(matches)
        weights = None
        if self.half_life_seasons:
            age = long["season"].max() - long["season"]
            weights = 0.5 ** (age.to_numpy() / self.half_life_seasons)
        X = self._encoder.fit_transform(long[["team", "opp", "is_home"]])
        self._model.fit(X, long["goals"].to_numpy(), sample_weight=weights)
        return self

    def expected_goals(
        self, home_teams, away_teams
    ) -> tuple[np.ndarray, np.ndarray]:
        home = pd.DataFrame({"team": list(home_teams), "opp": list(away_teams), "is_home": 1})
        away = pd.DataFrame({"team": list(away_teams), "opp": list(home_teams), "is_home": 0})
        return (
            self._model.predict(self._encoder.transform(home)),
            self._model.predict(self._encoder.transform(away)),
        )

    def outcome_probs(self, home_teams, away_teams) -> np.ndarray:
        lam_h, lam_a = self.expected_goals(home_teams, away_teams)
        return scoreline_outcome_probs(lam_h, lam_a)
