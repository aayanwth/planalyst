"""Tuning tables and the report generator, run end to end on a small synthetic league."""

import numpy as np
import pandas as pd
import pytest

from planalyst.ml import report, tune
from tests.conftest import make_league

# Ten seasons so the validation seasons (2018-19) have earlier seasons to train on.
LEAGUE = make_league(seasons=tuple(range(2014, 2024)), seed=3)
SEASONS = (2022, 2023)


def test_elo_validation_table_covers_the_grid_and_is_sorted():
    table = tune.elo_validation_table(LEAGUE, seasons=SEASONS)
    n = np.prod([len(v) for v in tune.ELO_GRID.values()])
    assert len(table) == n
    assert table["log_loss"].is_monotonic_increasing
    assert set(table["home_advantage"]) == set(tune.ELO_GRID["home_advantage"])
    assert np.isfinite(table["log_loss"]).all()


def test_synthetic_league_has_home_advantage_and_tuning_finds_it():
    """The generator gives the home side an edge, so zero home advantage must not be the best."""
    table = tune.elo_validation_table(LEAGUE, seasons=SEASONS)
    assert table.loc[0, "home_advantage"] > 0


def test_poisson_validation_table_is_sorted_over_the_full_grid():
    table = tune.poisson_validation_table(LEAGUE, seasons=SEASONS)
    assert len(table) == len(tune.POISSON_GRID["alpha"]) * len(tune.POISSON_GRID["half_life_seasons"])
    assert table["log_loss"].is_monotonic_increasing and np.isfinite(table["log_loss"]).all()


def test_xgb_validation_table_includes_the_legacy_and_reference_rows():
    table = tune.validation_table(LEAGUE, seasons=SEASONS)
    configs = " | ".join(table["config"])
    assert "legacy" in configs and "reference: logistic regression" in configs
    assert "production params (no class weights)" in configs
    assert table["log_loss"].is_monotonic_increasing


def test_blend_weight_grid_is_a_valid_simplex_and_contains_equal_weights():
    table = tune.blend_weight_table(LEAGUE, seasons=SEASONS, step=0.5)
    weights = table[["w_xgb", "w_elo", "w_poisson"]]
    assert np.allclose(weights.sum(axis=1), 1.0)
    assert (weights >= 0).all().all()
    assert len(table) == 6  # (0, .5, 1) on a 3-way simplex
    assert table["log_loss"].is_monotonic_increasing


def test_inverse_frequency_weights_balance_the_classes():
    y = np.array([0, 0, 0, 1])
    w = tune.inverse_frequency_weights(y)
    # each class receives the same total weight: n / n_classes
    totals = [w[y == k].sum() for k in (0, 1)]
    assert totals[0] == pytest.approx(totals[1])


def test_report_helpers():
    df = pd.DataFrame({"season": [2020], "x": [1.23456], "name": ["a|b"]})
    text = report.md_table(df)
    assert "| 2020 | 1.2346 | a|b |" in text  # ints stay ints, floats get 4 decimals
    assert report.verdict(0.1, 0.05, 0.2, "log loss", "A", "B").startswith("B is better")
    assert report.verdict(-0.1, -0.2, -0.05, "RPS", "A", "B").startswith("A is better")
    assert "no clear difference" in report.verdict(0.0, -0.1, 0.1, "RPS", "A", "B")


def test_report_builds_end_to_end_with_no_hand_written_numbers(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "load_matches", lambda source: LEAGUE)
    monkeypatch.setattr(report, "IMG", tmp_path)  # never touch the real docs/img
    text = report.build_report("csv", quick=True)

    for heading in (
        "## 1. Match-outcome model vs baselines",
        "### Is the difference real? Paired bootstrap",
        "## 3. Calibration",
        "## 4. How the model settings were chosen",
        "## 5. Title-race backtest",
    ):
        assert heading in text
    for model in ("prior", "elo_formula", "logit_elo", "poisson_glm", "xgb_full", "blend"):
        assert f"| {model} |" in text
    assert {p.name for p in tmp_path.iterdir()} == {
        "calibration_blend.png",
        "calibration_xgb.png",
        "title_backtest.png",
    }
    assert "nan" not in text.lower().replace("financial", "")  # no NaN leaked into a table
