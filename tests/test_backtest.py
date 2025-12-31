import numpy as np
import pandas as pd
import pytest

from planalyst.ml import backtest as bt
from planalyst.ml.predict import _proba_from_perspective, build_fixture_features
from planalyst.ml.train import FEATURE_COLUMNS


def test_final_table_orders_by_points_then_goal_difference():
    matches = pd.DataFrame(
        {
            "home_team_name": ["A", "B", "C"],
            "away_team_name": ["B", "C", "A"],
            "score_home": [1, 0, 0],
            "score_away": [0, 0, 3],
        }
    )
    table = bt.final_table(matches)
    # A: 3 (W vs B) + 3 (W at C) = 6; B: 0 + 1 = 1; C: 1 + 0 = 1 with a worse goal difference
    assert list(table.index) == ["A", "B", "C"]
    assert table.loc["A", "points"] == 6 and table.loc["A", "gd"] == 4


def test_state_at_checkpoint_only_uses_rounds_played(league):
    season, cp = 2023, 4
    standings, live, remaining = bt.state_at_checkpoint(league, season, cp)
    played = league[(league["season"] == season) & (league["matchday"] <= cp)]
    assert (remaining["matchday"] > cp).all()
    assert len(remaining) + len(played) == len(league[league["season"] == season])
    expected = bt.final_table(played)["points"]
    got = standings.set_index("team")["current_points"]
    assert got.sort_index().equals(expected.sort_index().astype(got.dtype))
    assert set(FEATURE_COLUMNS) - {"is_home", "elo_diff"} <= set(live.columns)
    assert live["elo_rating"].notna().all()


def test_backtest_season_outputs_valid_title_distributions(league):
    res = bt.backtest_season(league, 2023, checkpoints=(3, 8), n_simulations=300, seed=3)
    sums = res.groupby(["checkpoint", "source"])["title_prob"].sum()
    assert np.allclose(sums, 1.0)
    assert res.groupby(["checkpoint", "source"])["is_champion"].sum().eq(1).all()
    scores = bt.score_backtest(res)
    assert scores["brier"].between(0, 2).all() and scores["p_champion"].between(0, 1).all()


def test_backtest_at_the_final_round_has_nothing_left_to_simulate(league):
    last_round = int(league.loc[league["season"] == 2023, "matchday"].max())
    res = bt.backtest_season(league, 2023, checkpoints=(last_round,), n_simulations=50)
    scores = bt.score_backtest(res)
    assert (scores["p_champion"] == 1.0).all()  # the table is final, so the champion is certain
    assert (scores["brier"] == 0.0).all()


class _StubModel:
    """Predicts fixed class probabilities in the model's own class order."""

    classes_ = np.array([0, 1, 2])

    def predict_proba(self, x):
        return np.tile([0.2, 0.3, 0.5], (len(x), 1))


class _StubEncoder:
    def inverse_transform(self, classes):
        return np.array(["D", "L", "W"])[list(classes)]


def test_probabilities_are_mapped_through_the_label_encoder():
    out = _proba_from_perspective(_StubModel(), np.zeros(len(FEATURE_COLUMNS)), _StubEncoder())
    assert out == pytest.approx({"D": 0.2, "L": 0.3, "W": 0.5})


def test_model_failure_falls_back_to_priors_that_sum_to_one():
    class Broken:
        classes_ = np.array([0, 1, 2])

        def predict_proba(self, x):
            raise RuntimeError("boom")

    out = _proba_from_perspective(Broken(), np.zeros(3), None)
    assert sum(out.values()) == pytest.approx(1.0)


def test_fixture_features_follow_feature_column_order_and_venue():
    live = pd.DataFrame(
        {
            "team": ["H", "A"],
            "matchday": [3, 3],
            **{c: [1.0, 2.0] for c in FEATURE_COLUMNS},
        }
    )
    live["elo_rating"] = [1600.0, 1500.0]
    fixture = pd.Series({"home_team_name": "H", "away_team_name": "A"})
    home = build_fixture_features(fixture, live, is_home=True)
    away = build_fixture_features(fixture, live, is_home=False)
    i_home, i_diff = FEATURE_COLUMNS.index("is_home"), FEATURE_COLUMNS.index("elo_diff")
    assert (home[i_home], away[i_home]) == (1.0, 0.0)
    assert (home[i_diff], away[i_diff]) == (100.0, -100.0)
    assert len(home) == len(FEATURE_COLUMNS)
