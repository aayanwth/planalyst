import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text

from planalyst.ml.predict import (
    BLEND_WEIGHTS,
    blend_probs,
    elo_outcome_probs,
    empirical_margins,
    record_fixture_predictions,
    record_history,
    score_fixtures,
    simulate_season,
    simulate_title_race,
)


def test_elo_probs_normalised_and_ordered_by_strength():
    p = elo_outcome_probs(1500, 1500)
    assert p.sum() == pytest.approx(1)
    assert p[0] > p[2]  # equal ratings still favour the home side (home advantage)
    stronger_home = elo_outcome_probs(1700, 1500)
    assert stronger_home[0] > p[0] > stronger_home[2]


def test_blend_weights_and_normalisation():
    comps = {
        "xgb": np.array([0.7, 0.2, 0.1]),
        "elo": np.array([0.3, 0.3, 0.4]),
        "poisson": np.array([0.5, 0.25, 0.25]),
    }
    assert np.allclose(blend_probs(comps, {"elo": 1.0}), comps["elo"])
    assert np.allclose(blend_probs(comps, {"xgb": 1.0}), comps["xgb"])
    mixed = blend_probs(comps)
    assert mixed.sum() == pytest.approx(1)
    assert np.allclose(mixed, np.mean(list(comps.values()), axis=0))  # equal weights by default
    assert sum(BLEND_WEIGHTS.values()) == pytest.approx(1)


def test_blend_handles_a_batch_of_fixtures():
    comps = {k: np.tile([0.5, 0.3, 0.2], (4, 1)) for k in BLEND_WEIGHTS}
    out = blend_probs(comps)
    assert out.shape == (4, 3) and np.allclose(out.sum(axis=1), 1)


def _race(probs, base_points, base_gd, home, away, n=4000, seed=1, margins=None):
    return simulate_title_race(
        np.array(home, dtype=int),
        np.array(away, dtype=int),
        np.array(probs, dtype=float).reshape(-1, 3),
        np.array(base_points, dtype=float),
        np.array(base_gd, dtype=float),
        n,
        seed,
        margins,
    )


def test_simulation_is_reproducible_with_seed():
    args = ([[0.5, 0.3, 0.2]] * 3, [10, 10, 10], [0, 0, 0], [0, 1, 2], [1, 2, 0])
    a = _race(*args, n=500, seed=7)
    b = _race(*args, n=500, seed=7)
    assert np.array_equal(a["title_counts"], b["title_counts"])


def test_simulation_invariants():
    n = 2000
    sim = _race(
        [[0.45, 0.25, 0.30]] * 6,
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 1, 2, 3, 0, 2],
        [1, 2, 3, 0, 2, 0],
        n=n,
    )
    assert sim["title_counts"].sum() == n  # exactly one champion per simulation
    assert sim["avg_rank"].sum() == pytest.approx(4 * 5 / 2)  # ranks 1..4 each used once
    assert 6 * 2 <= sim["avg_points"].sum() <= 6 * 3  # 2 points per draw, 3 per decisive match


def test_certain_results_decide_the_title():
    # Team 0 wins at home against team 1 and again away at team 1.
    sim = _race([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]], [0, 0], [0, 0], [0, 1], [1, 0], n=300)
    assert sim["title_counts"][0] == 300


def test_leader_with_no_fixtures_left_always_wins():
    sim = _race(np.zeros((0, 3)), [70, 65, 60], [30, 20, 10], [], [], n=100)
    assert list(sim["title_counts"]) == [100, 0, 0]


def test_goal_difference_breaks_points_ties():
    sim = _race(np.zeros((0, 3)), [50, 50], [5, 12], [], [], n=50)
    assert list(sim["title_counts"]) == [0, 50]


def test_title_odds_follow_strength():
    strong_home = [0.8, 0.1, 0.1]
    strong_away = [0.1, 0.1, 0.8]
    sim = _race(
        [strong_home, strong_home, strong_away, strong_away],
        [0, 0, 0],
        [0, 0, 0],
        [0, 0, 1, 2],
        [1, 2, 0, 0],
        n=4000,
    )
    assert sim["title_counts"][0] > sim["title_counts"][1]
    assert sim["title_counts"][0] > sim["title_counts"][2]


def test_simulation_rank_outputs_are_consistent():
    n = 1500
    sim = _race(
        [[0.45, 0.25, 0.30]] * 6,
        [3, 2, 1, 0, 0],
        [1, 0, 0, 0, 0],
        [0, 1, 2, 3, 4, 0],
        [1, 2, 3, 4, 0, 2],
        n=n,
    )
    counts = sim["rank_counts"]
    assert counts.shape == (5, 5)
    assert (counts.sum(axis=1) == n).all()  # each team finishes somewhere every simulation
    assert (counts.sum(axis=0) == n).all()  # each position is filled once per simulation
    assert np.array_equal(counts[:, 0], sim["title_counts"])
    assert (sim["points_p10"] <= sim["avg_points"]).all()
    assert (sim["avg_points"] <= sim["points_p90"]).all()


def test_winning_margins_come_from_the_supplied_pool():
    # Teams 0 and 1 are level and each certain to win one match, so the title is decided by
    # which team's simulated winning margin is larger (ties go to team 0 by stable ordering).
    probs = [[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]]
    args = (probs, [10, 10, 0, 0], [0, 0, 0, 0], [0, 1], [2, 3])
    fixed = _race(*args, n=200, margins=np.array([5]))
    assert list(fixed["title_counts"][:2]) == [200, 0]  # identical margins -> always a tie
    mixed = _race(*args, n=2000, margins=np.array([1, 9]))
    assert mixed["title_counts"][1] > 0 and mixed["title_counts"][0] > mixed["title_counts"][1]


def test_empirical_margins_use_only_decisive_matches():
    m = pd.DataFrame({"score_home": [2, 1, 0, 4], "score_away": [0, 1, 3, 0]})
    assert sorted(empirical_margins(m)) == [2, 3, 4]
    draws_only = pd.DataFrame({"score_home": [1], "score_away": [1]})
    assert len(empirical_margins(draws_only)) > 0  # falls back to the documented default pool


class _XgbStub:
    classes_ = np.array([0, 1, 2])

    def predict_proba(self, x):
        return np.tile([0.2, 0.3, 0.5], (len(x), 1))


class _EncoderStub:
    def inverse_transform(self, classes):
        return np.array(["D", "L", "W"])[list(classes)]


class _GoalsStub:
    def outcome_probs(self, home, away):
        return np.tile([0.5, 0.25, 0.25], (len(home), 1))


def test_score_fixtures_blends_components_and_keeps_fixture_columns():
    fixtures = pd.DataFrame(
        {
            "id": [1, 2],
            "matchday": [6, 6],
            "home_team_name": ["A", "C"],
            "away_team_name": ["B", "D"],
        }
    )
    live = pd.DataFrame(
        {"team": ["A", "B", "C", "D"], "matchday": 5, "elo_rating": [1700.0, 1400.0, 1500.0, 1500.0]}
    )
    out = score_fixtures(_XgbStub(), fixtures, live, _EncoderStub(), _GoalsStub())
    assert list(out["id"]) == [1, 2]
    assert np.allclose(out[["p_home", "p_draw", "p_away"]].sum(axis=1), 1)
    # only the Elo component differs between fixtures, so the stronger home side must score higher
    assert out.loc[0, "p_home"] > out.loc[1, "p_home"]
    assert out.loc[0, "p_away"] < out.loc[1, "p_away"]


def test_score_fixtures_with_no_fixtures():
    empty = pd.DataFrame({"id": [], "home_team_name": [], "away_team_name": []})
    out = score_fixtures(_XgbStub(), empty, pd.DataFrame(), _EncoderStub(), _GoalsStub())
    assert out.empty


def test_simulate_season_reports_title_top4_and_relegation_probabilities():
    standings = pd.DataFrame(
        {
            "team": list("ABCDEF"),
            "current_points": [30, 20, 15, 10, 5, 0],
            "current_gd": [10, 5, 0, -2, -5, -8],
        }
    )
    fixtures = pd.DataFrame(
        {
            "home_team_name": ["A", "B"],
            "away_team_name": ["F", "E"],
            "p_home": [0.6, 0.5],
            "p_draw": [0.2, 0.3],
            "p_away": [0.2, 0.2],
        }
    )
    out = simulate_season(fixtures, standings, n_simulations=300, seed=1).set_index("team_name")
    assert out["win_probability"].sum() == pytest.approx(1.0)
    assert out.loc["A", "win_probability"] > 0.9
    assert out["top4_probability"].sum() == pytest.approx(4.0, abs=0.01)  # four top-four places
    assert out["relegation_probability"].sum() == pytest.approx(3.0, abs=0.01)
    assert out.loc["F", "relegation_probability"] > out.loc["B", "relegation_probability"]


def test_simulate_season_without_standings_is_empty():
    assert simulate_season(pd.DataFrame(), pd.DataFrame()).empty


def _preds(matchweek, p_a):
    return pd.DataFrame(
        {
            "team_name": ["Arsenal", "Chelsea"],
            "win_probability": [p_a, 1 - p_a],
            "avg_final_points": [80.0, 70.0],
            "avg_final_rank": [1.2, 1.8],
            "simulations_won": [int(p_a * 1000), int((1 - p_a) * 1000)],
            "total_simulations": [1000, 1000],
            "top4_probability": [0.9, 0.8],
            "relegation_probability": [0.0, 0.1],
            "points_p10": [75.0, 65.0],
            "points_p90": [85.0, 75.0],
            "matchweek": matchweek,
            "season": 2026,
            "model_version": "blend_v3",
        }
    )


def test_history_is_append_only_across_matchweeks_but_idempotent_per_run(sqlite_engine):
    assert record_history(sqlite_engine, _preds(5, 0.6)) == 2
    record_history(sqlite_engine, _preds(6, 0.7))
    record_history(sqlite_engine, _preds(6, 0.8))  # re-run of matchweek 6 replaces its rows
    with sqlite_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT matchweek, win_probability FROM gold.title_prediction_history "
                "WHERE team_name = 'Arsenal' ORDER BY matchweek"
            )
        ).all()
    assert rows == [(5, pytest.approx(0.6)), (6, pytest.approx(0.8))]


def test_history_ignores_empty_predictions(sqlite_engine):
    assert record_history(sqlite_engine, pd.DataFrame()) == 0


def test_history_table_from_an_older_schema_is_migrated_in_place(sqlite_engine):
    with sqlite_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE gold.title_prediction_history ("
                "season INTEGER NOT NULL, matchweek INTEGER NOT NULL, model_version TEXT NOT NULL, "
                "team_name TEXT NOT NULL, win_probability DOUBLE PRECISION, "
                "avg_final_points DOUBLE PRECISION, avg_final_rank DOUBLE PRECISION, "
                "simulations_won INTEGER, total_simulations INTEGER, "
                "scored_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
                "PRIMARY KEY (season, matchweek, model_version, team_name))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO gold.title_prediction_history "
                "(season, matchweek, model_version, team_name, win_probability) "
                "VALUES (2026, 4, 'xgb_v2', 'Arsenal', 0.3)"
            )
        )
    assert record_history(sqlite_engine, _preds(5, 0.6)) == 2
    with sqlite_engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text("PRAGMA gold.table_info(title_prediction_history)")).all()}
        old = conn.execute(
            text(
                "SELECT win_probability, top4_probability FROM gold.title_prediction_history "
                "WHERE matchweek = 4"
            )
        ).one()
    assert {"top4_probability", "relegation_probability", "points_p10", "points_p90"} <= cols
    assert old[0] == pytest.approx(0.3) and old[1] is None  # old rows kept, new columns empty


def _scored(ids, p=(0.5, 0.3, 0.2)):
    return pd.DataFrame(
        {
            "id": ids,
            "matchday": 6,
            "utc_date": pd.Timestamp("2026-10-10 15:00", tz="UTC"),
            "home_team_name": "A",
            "away_team_name": "B",
            "p_home": p[0],
            "p_draw": p[1],
            "p_away": p[2],
        }
    )


def test_fixture_forecasts_refresh_until_kickoff_then_freeze(sqlite_engine):
    record_fixture_predictions(sqlite_engine, _scored([1, 2]), 2026)
    # next run: match 1 has been played (no longer in the unplayed set); match 2 is refreshed
    record_fixture_predictions(sqlite_engine, _scored([2, 3], p=(0.1, 0.1, 0.8)), 2026)
    with sqlite_engine.connect() as conn:
        rows = dict(conn.execute(text("SELECT match_id, p_home FROM gold.fixture_predictions")).all())
    assert rows[1] == pytest.approx(0.5)  # frozen at its last pre-match forecast
    assert rows[2] == pytest.approx(0.1)  # refreshed
    assert rows[3] == pytest.approx(0.1)  # new
    assert len(rows) == 3


def test_fixture_forecasts_ignore_empty_input(sqlite_engine):
    assert record_fixture_predictions(sqlite_engine, pd.DataFrame(), 2026) == 0
