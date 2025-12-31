import numpy as np
import pandas as pd
import pytest

from planalyst.ml.elo import (
    DEFAULT_ELO,
    DEFAULT_PARAMS,
    EloParams,
    expected_home_score,
    outcome_probs,
    outcome_probs_array,
    pre_match_long,
    run_elo,
)


def _m(rows):
    return pd.DataFrame(
        rows, columns=["season", "matchday", "home_team_name", "away_team_name", "score_home", "score_away"]
    )


NEUTRAL = EloParams(home_advantage=0.0, season_regression=0.0, new_team_elo=DEFAULT_ELO)


def test_expected_score_is_half_when_equal_and_home_advantage_shifts_it():
    assert expected_home_score(1500, 1500) == pytest.approx(0.5)
    assert expected_home_score(1500, 1500, home_advantage=100) > 0.5
    # +400 points is a 10:1 odds ratio
    assert expected_home_score(1900, 1500) == pytest.approx(10 / 11)


def test_outcome_probs_sum_to_one_and_vector_matches_scalar():
    pairs = [(1500, 1500), (1700, 1450), (1400, 1650)]
    vec = outcome_probs_array([p[0] for p in pairs], [p[1] for p in pairs])
    for row, (h, a) in zip(vec, pairs):
        assert row.sum() == pytest.approx(1)
        assert np.allclose(row, outcome_probs(h, a))
    assert vec[0, 1] == pytest.approx(DEFAULT_PARAMS.draw_prob)


def test_ratings_are_zero_sum_within_a_season_of_established_teams():
    matches = _m([(1, 1, "A", "B", 2, 0), (1, 1, "C", "D", 1, 1), (1, 2, "A", "C", 0, 3)])
    ratings, _ = run_elo(matches, NEUTRAL)
    assert sum(ratings.values()) == pytest.approx(4 * DEFAULT_ELO)


def test_pre_match_ratings_exclude_the_match_itself():
    matches = _m([(1, 1, "A", "B", 5, 0), (1, 2, "A", "B", 0, 0)])
    ratings, pre = run_elo(matches, NEUTRAL)
    assert pre.loc[0, ["home_elo", "away_elo"]].tolist() == [DEFAULT_ELO, DEFAULT_ELO]
    assert pre.loc[1, "home_elo"] > DEFAULT_ELO > pre.loc[1, "away_elo"]  # reflects match 1 only
    assert ratings["A"] > DEFAULT_ELO


def test_home_advantage_means_a_home_win_is_less_surprising():
    matches = _m([(1, 1, "A", "B", 1, 0)])
    plain, _ = run_elo(matches, NEUTRAL)
    adv, _ = run_elo(matches, EloParams(home_advantage=100, new_team_elo=DEFAULT_ELO))
    assert adv["A"] < plain["A"]  # expected to win already, so it gains less


def test_bigger_margin_moves_ratings_more():
    small, _ = run_elo(_m([(1, 1, "A", "B", 1, 0)]), NEUTRAL)
    big, _ = run_elo(_m([(1, 1, "A", "B", 4, 0)]), NEUTRAL)
    assert big["A"] > small["A"] > DEFAULT_ELO


def test_promoted_team_starts_lower_but_only_after_the_first_season():
    params = EloParams(new_team_elo=1400.0)
    matches = _m([(1, 1, "A", "B", 1, 0), (2, 1, "A", "C", 1, 0)])
    _, pre = run_elo(matches, params)
    assert pre.loc[0, "away_elo"] == DEFAULT_ELO  # first season: everyone starts level
    assert pre.loc[1, "away_elo"] == 1400.0  # C is new in season 2


def test_season_regression_pulls_ratings_toward_the_mean_at_season_start():
    matches = _m([(1, 1, "A", "B", 6, 0), (2, 1, "A", "B", 0, 0)])
    keep, pre_keep = run_elo(matches, EloParams(season_regression=0.0))
    pulled, pre_pull = run_elo(matches, EloParams(season_regression=0.5))
    a_before = pre_keep.loc[1, "home_elo"]
    assert pre_pull.loc[1, "home_elo"] == pytest.approx(DEFAULT_ELO + 0.5 * (a_before - DEFAULT_ELO))
    assert pulled["A"] < keep["A"]


def test_order_of_input_rows_does_not_matter():
    rows = [(1, 2, "A", "B", 1, 0), (1, 1, "B", "A", 2, 2), (2, 1, "A", "B", 0, 1)]
    a, _ = run_elo(_m(rows), DEFAULT_PARAMS)
    b, _ = run_elo(_m(rows[::-1]), DEFAULT_PARAMS)
    assert a == pytest.approx(b)


def test_pre_match_long_has_two_rows_per_match_with_opponent_rating():
    _, pre = run_elo(_m([(1, 1, "A", "B", 1, 0)]), NEUTRAL)
    long = pre_match_long(pre).set_index("team")
    assert len(long) == 2
    assert long.loc["A", "opp_elo"] == long.loc["B", "elo_rating"]
