import numpy as np
import pytest

from planalyst.ml import evaluation as ev


def test_outcome_index():
    assert list(ev.outcome_index([2, 1, 0], [0, 1, 3])) == [0, 1, 2]


def test_rps_known_values():
    y = np.array([0, 2])
    perfect = np.array([[1, 0, 0], [0, 0, 1.0]])
    assert ev.rps_per_match(perfect, y).sum() == 0
    worst = np.array([[0, 0, 1.0], [1.0, 0, 0]])
    assert np.allclose(ev.rps_per_match(worst, y), 1.0)
    # Hand-computed: p=(.5,.3,.2), home win -> ((.5-1)^2 + (.8-1)^2) / 2 = 0.145
    assert ev.rps_per_match(np.array([[0.5, 0.3, 0.2]]), np.array([0]))[0] == pytest.approx(0.145)


def test_rps_respects_outcome_ordering():
    """Predicting a draw when the home side won is a smaller miss than predicting an away win."""
    y = np.array([0])
    near = ev.rps_per_match(np.array([[0, 1.0, 0]]), y)
    far = ev.rps_per_match(np.array([[0, 0, 1.0]]), y)
    assert near < far


def test_brier_and_log_loss():
    p = np.array([[0.6, 0.3, 0.1]])
    y = np.array([0])
    assert ev.brier_per_match(p, y)[0] == pytest.approx(0.16 + 0.09 + 0.01)
    assert ev.log_loss_per_match(p, y)[0] == pytest.approx(-np.log(0.6))
    assert np.isfinite(ev.log_loss_per_match(np.array([[0, 1.0, 0]]), np.array([0]))[0])


def test_calibration_counts_and_calibrated_forecast():
    rng = np.random.default_rng(1)
    n = 8000
    probs = rng.dirichlet([3, 2, 2], size=n)
    y = np.array([rng.choice(3, p=p) for p in probs])  # outcomes drawn from the probabilities
    table = ev.calibration_table(probs, y, n_bins=10)
    for outcome in ev.OUTCOMES:
        assert table.loc[table["outcome"] == outcome, "n"].sum() == n
    assert ev.expected_calibration_error(table) < 0.05


def test_calibration_flags_overconfidence():
    probs = np.tile([0.9, 0.05, 0.05], (1000, 1))
    y = np.array([0] * 500 + [1] * 250 + [2] * 250)  # home wins half the time, not 90%
    assert ev.expected_calibration_error(ev.calibration_table(probs, y)) > 0.2


def test_paired_bootstrap_sign_and_ci():
    rng = np.random.default_rng(0)
    b = rng.normal(1.0, 0.1, 500)
    mean, lo, hi = ev.paired_bootstrap(b - 0.05, b, n_boot=500)
    assert mean == pytest.approx(-0.05) and hi < 0
    same = ev.paired_bootstrap(b, b, n_boot=200)
    assert same[0] == 0 and same[1] <= 0 <= same[2]


def test_prior_probs():
    p = ev.prior_probs(np.array([0, 0, 1, 2]), 3)
    assert p.shape == (3, 3) and np.allclose(p.sum(axis=1), 1) and p[0, 0] == 0.5


def test_walk_forward_on_synthetic_league(league):
    meta, probs = ev.walk_forward(league, [2022, 2023])
    n = len(meta)
    assert set(meta["season"]) == {2022, 2023}
    assert meta["match_id"].is_unique
    for name in ev.MODEL_ORDER:
        assert probs[name].shape == (n, 3)
        assert np.allclose(probs[name].sum(axis=1), 1, atol=1e-6)
        assert (probs[name] >= 0).all()
    y = meta["y"].to_numpy()
    # Strength is built into the data, so Elo must beat the class-frequency baseline.
    elo_loss = ev.log_loss_per_match(probs["elo_formula"], y).mean()
    assert elo_loss < ev.log_loss_per_match(probs["prior"], y).mean()


def test_walk_forward_does_not_see_the_test_season_results(league):
    """Flipping late-season results must not change predictions for early-season matches:
    those predictions can only depend on results that happened before them."""
    scrambled = league.copy()
    late = (scrambled["season"] == 2023) & (scrambled["matchday"] > 6)
    flipped = scrambled.loc[late, ["score_away", "score_home"]].to_numpy()
    scrambled.loc[late, ["score_home", "score_away"]] = flipped
    meta_a, probs_a = ev.walk_forward(league, [2023])
    _, probs_b = ev.walk_forward(scrambled, [2023])
    early = league.set_index("id").loc[meta_a["match_id"], "matchday"].to_numpy() <= 6
    assert early.any()
    assert np.allclose(probs_a["xgb_full"][early], probs_b["xgb_full"][early])
    assert np.allclose(probs_a["elo_formula"][early], probs_b["elo_formula"][early])


def test_walk_forward_requires_earlier_seasons(league):
    with pytest.raises(ValueError):
        ev.walk_forward(league, [2018])
