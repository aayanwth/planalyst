import pandas as pd

from planalyst.ml.features import (
    build_feature_frame,
    compute_features,
    compute_target,
    unpivot_to_team_level,
)
from planalyst.ml.train import (
    DEFAULT_ELO,
    FEATURE_COLUMNS,
    add_elo_features,
    compute_elo_ratings,
    prepare_training_frame,
)


def _two_team_season():
    # A beats B 2-0 at home, then they draw 1-1 (B at home), then B beat A 3-0 (B at home).
    return pd.DataFrame(
        {
            "id": [1, 2, 3],
            "matchday": [1, 2, 3],
            "season": [2020] * 3,
            "season_label": ["2020-2021"] * 3,
            "home_team_name": ["A", "B", "B"],
            "away_team_name": ["B", "A", "A"],
            "score_home": [2, 1, 3],
            "score_away": [0, 1, 0],
        }
    )


def test_unpivot_gives_two_rows_per_match_with_correct_points():
    rows = unpivot_to_team_level(_two_team_season())
    assert len(rows) == 6
    md1 = rows[rows["matchday"] == 1].set_index("team")
    assert (md1.loc["A", "points"], md1.loc["B", "points"]) == (3, 0)
    assert (md1.loc["A", "result"], md1.loc["B", "result"]) == ("W", "L")
    md2 = rows[rows["matchday"] == 2]
    assert (md2["points"] == 1).all() and (md2["result"] == "D").all()


def test_cumulative_features_and_position():
    feats = compute_features(unpivot_to_team_level(_two_team_season()))
    a = feats[feats["team"] == "A"].sort_values("matchday")
    assert list(a["season_points"]) == [3, 4, 4]
    assert list(a["season_gd"]) == [2, 2, -1]
    md1 = feats[feats["matchday"] == 1].set_index("team")
    assert (md1.loc["A", "season_position"], md1.loc["B", "season_position"]) == (1, 2)


def test_target_is_next_match_and_last_match_is_dropped():
    feats = compute_features(unpivot_to_team_level(_two_team_season()))
    out = compute_target(feats)
    a = out[out["team"] == "A"].sort_values("matchday")
    assert list(a["matchday"]) == [1, 2]  # matchday 3 has no next match
    assert list(a["next_result"]) == ["D", "L"]  # A: W, D, L


def test_features_never_use_the_result_they_predict(league):
    """Changing a team's NEXT result must not change any feature on the row that predicts it."""
    base = build_feature_frame(league)
    row = base[(base["season"] == 2020) & (base["team"] == "Alpha") & (base["matchday"] == 4)]
    row_id = row["id"].iloc[0]
    nxt = league[
        (league["season"] == 2020)
        & (league["matchday"] == 5)
        & ((league["home_team_name"] == "Alpha") | (league["away_team_name"] == "Alpha"))
    ].index[0]
    changed = league.copy()
    changed.loc[nxt, ["score_home", "score_away"]] = [9, 0]
    after = build_feature_frame(changed)
    cols = ["rolling_points_5", "rolling_gd_5", "season_points", "season_gd", "win_rate"]
    before_row = base[base["id"] == row_id].set_index("team").loc["Alpha", cols]
    after_row = after[after["id"] == row_id].set_index("team").loc["Alpha", cols]
    assert before_row.equals(after_row)


def test_elo_is_zero_sum_and_strength_orders_ratings(league):
    elo = compute_elo_ratings(league)
    assert abs(sum(elo.values()) - DEFAULT_ELO * len(elo)) < 1e-6
    assert elo["Alpha"] > elo["Foxtrot"]


def test_bigger_win_moves_elo_more():
    def after(score_home):
        m = pd.DataFrame(
            {
                "season": [1],
                "matchday": [1],
                "home_team_name": ["H"],
                "away_team_name": ["A"],
                "score_home": [score_home],
                "score_away": [0],
            }
        )
        return compute_elo_ratings(m)["H"]

    assert after(3) > after(1) > DEFAULT_ELO


def test_elo_feature_is_recorded_before_the_match():
    matches = _two_team_season()
    out = add_elo_features(compute_features(unpivot_to_team_level(matches)), matches)
    first = out[out["matchday"] == 1]
    assert (first["elo_rating"] == DEFAULT_ELO).all()  # nothing has happened yet
    assert (first["elo_diff"] == 0).all()


def test_align_to_next_match_shifts_venue_one_row_back(league):
    raw = build_feature_frame(league)
    frame = prepare_training_frame(raw, league)
    pick = lambda d: d[(d["season"] == 2020) & (d["team"] == "Alpha")].sort_values("matchday")  # noqa: E731
    a, r = pick(frame), pick(raw)
    assert list(a["is_home"].iloc[:-1]) == list(r["is_home"].iloc[1:])
    assert pd.isna(a["is_home"].iloc[-1])


def test_prepared_frame_has_every_model_feature(league):
    frame = prepare_training_frame(build_feature_frame(league), league)
    assert set(FEATURE_COLUMNS) <= set(frame.columns)
