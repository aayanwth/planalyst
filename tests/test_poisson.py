import numpy as np
import pandas as pd
import pytest
from scipy.stats import poisson

from planalyst.ml.poisson import PoissonGoalModel, scoreline_outcome_probs


def test_scoreline_probabilities_match_a_hand_computation():
    # lambda_home = lambda_away: the match is symmetric, so home and away win equally often
    p = scoreline_outcome_probs(np.array([1.2]), np.array([1.2]))[0]
    assert p.sum() == pytest.approx(1)
    assert p[0] == pytest.approx(p[2])
    # P(0-0) alone is exp(-2.4); draws must be at least that large
    assert p[1] > poisson.pmf(0, 1.2) ** 2

    # P(home win) for (2.0, 0.5) computed independently by brute force
    goals = range(0, 11)
    brute = sum(
        poisson.pmf(i, 2.0) * poisson.pmf(j, 0.5) for i in goals for j in goals if i > j
    )
    got = scoreline_outcome_probs(np.array([2.0]), np.array([0.5]))[0]
    assert got[0] == pytest.approx(brute, rel=0.01)
    assert got[0] > 0.7 and got[0] > got[1] > got[2]


def test_more_expected_goals_means_more_wins():
    low = scoreline_outcome_probs(np.array([1.0]), np.array([1.0]))[0]
    high = scoreline_outcome_probs(np.array([2.0]), np.array([1.0]))[0]
    assert high[0] > low[0] and high[2] < low[2]


def _matches():
    # Strong attack "Alpha" scores a lot; weak "Zed" concedes a lot.
    rows = []
    for season in (1, 2, 3):
        for h, a, sh, sa in [
            ("Alpha", "Mid", 3, 0), ("Mid", "Alpha", 1, 3), ("Alpha", "Zed", 4, 0),
            ("Zed", "Alpha", 0, 3), ("Mid", "Zed", 2, 0), ("Zed", "Mid", 0, 2),
            ("Mid", "Alpha", 0, 2), ("Zed", "Mid", 1, 3),
        ]:
            rows.append((season, h, a, sh, sa))
    return pd.DataFrame(rows, columns=["season", "home_team_name", "away_team_name", "score_home", "score_away"])


def test_fitted_model_ranks_teams_by_strength():
    model = PoissonGoalModel(alpha=0.001).fit(_matches())
    probs = model.outcome_probs(["Alpha", "Zed"], ["Zed", "Alpha"])
    assert probs[0, 0] > 0.7  # Alpha at home to Zed
    assert probs[1, 2] > 0.7  # Zed at home to Alpha is still an away win
    assert np.allclose(probs.sum(axis=1), 1)


def test_home_side_is_expected_to_score_more_than_it_would_away():
    model = PoissonGoalModel(alpha=0.001).fit(_matches())
    home_goals, away_goals = model.expected_goals(["Mid"], ["Mid"])
    assert home_goals[0] > away_goals[0]  # the fitted home effect is positive in this data


def test_unseen_team_gets_average_strength_instead_of_failing():
    model = PoissonGoalModel(alpha=0.01).fit(_matches())
    probs = model.outcome_probs(["Newcomer"], ["Alpha"])
    assert probs.shape == (1, 3) and np.isfinite(probs).all() and probs.sum() == pytest.approx(1)
    assert probs[0, 2] > probs[0, 0]  # still loses to the strongest side


def test_recency_weighting_changes_the_fit():
    flip = _matches()
    flip.loc[flip["season"] == 3, ["score_home", "score_away"]] = flip.loc[
        flip["season"] == 3, ["score_away", "score_home"]
    ].to_numpy()
    equal = PoissonGoalModel(alpha=0.001, half_life_seasons=None).fit(flip)
    recent = PoissonGoalModel(alpha=0.001, half_life_seasons=0.5).fit(flip)
    p_equal = equal.outcome_probs(["Alpha"], ["Zed"])[0, 0]
    p_recent = recent.outcome_probs(["Alpha"], ["Zed"])[0, 0]
    assert p_recent != pytest.approx(p_equal, abs=1e-3)
