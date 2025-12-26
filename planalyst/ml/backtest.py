"""
PLanalyst — Title-race backtest.

Replays a finished season round by round. At each checkpoint the model is trained on
EARLIER seasons only, the standings and form are frozen as they were after that round, the
remaining fixtures are simulated with predict.simulate_title_race, and the title
probabilities are compared with who actually won.

Four probability sources are compared:
  elo      Elo-only fixture probabilities
  poisson  Poisson goals model only
  xgb      XGBoost only
  blend    the production mix (equal weights, predict.BLEND_WEIGHTS)

The Poisson model is refit at every checkpoint on earlier seasons plus the current season's
results so far, exactly as production refits it on all played matches.

Scores per checkpoint: probability given to the eventual champion, and the multi-class Brier
score of the title distribution, sum_t (p_t - 1[t is champion])^2 (0 = perfect, 2 = worst).
One champion per season is a tiny sample; treat results as a sanity check, not a verdict.
"""

from __future__ import annotations

import pandas as pd
from sklearn.preprocessing import LabelEncoder

from planalyst.ml.features import build_feature_frame, compute_features, unpivot_to_team_level
from planalyst.ml.poisson import PoissonGoalModel
from planalyst.ml.predict import (
    BLEND_WEIGHTS,
    blend_probs,
    empirical_margins,
    fixture_components,
    simulate_title_race,
)
from planalyst.ml.train import (
    FEATURE_COLUMNS,
    add_advanced_features,
    compute_elo_ratings,
    fit_model,
    prepare_training_frame,
)

DEFAULT_CHECKPOINTS = (5, 10, 15, 20, 25, 30, 35)
SOURCES = {
    "elo": {"elo": 1.0},
    "poisson": {"poisson": 1.0},
    "xgb": {"xgb": 1.0},
    "blend": BLEND_WEIGHTS,
}


def final_table(season_matches: pd.DataFrame) -> pd.DataFrame:
    """Points and goal difference after every match of the season."""
    rows = []
    for _, m in season_matches.iterrows():
        gd = m["score_home"] - m["score_away"]
        hp, ap = (3, 0) if gd > 0 else (1, 1) if gd == 0 else (0, 3)
        rows.append((m["home_team_name"], hp, gd))
        rows.append((m["away_team_name"], ap, -gd))
    table = pd.DataFrame(rows, columns=["team", "points", "gd"]).groupby("team").sum()
    return table.sort_values(["points", "gd"], ascending=False)


def train_on_earlier_seasons(matches: pd.DataFrame, season: int):
    """Production model trained only on seasons before `season`."""
    prior = matches[matches["season"] < season]
    frame = prepare_training_frame(build_feature_frame(prior), prior)
    frame = frame.dropna(subset=FEATURE_COLUMNS + ["next_result"])
    le = LabelEncoder()
    y = le.fit_transform(frame["next_result"])
    return fit_model(frame[FEATURE_COLUMNS].to_numpy(), y), le


def state_at_checkpoint(
    matches: pd.DataFrame, season: int, checkpoint: int
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(standings, live_features, remaining_fixtures) as they stood after round `checkpoint`."""
    season_matches = matches[matches["season"] == season]
    played = season_matches[season_matches["matchday"] <= checkpoint]
    remaining = season_matches[season_matches["matchday"] > checkpoint]

    state = add_advanced_features(compute_features(unpivot_to_team_level(played)))
    latest = state.sort_values("matchday").groupby("team").tail(1).copy()

    # Post-match Elo from every result before the cut-off (matches the next-match alignment
    # used in training, where a team's Elo only changes when it plays).
    history = matches[(matches["season"] < season) | matches.index.isin(played.index)]
    elo = compute_elo_ratings(history)
    latest["elo_rating"] = latest["team"].map(elo)
    latest["is_home"] = 0.5  # overwritten per fixture

    standings = pd.DataFrame(
        {
            "team": latest["team"],
            "last_matchweek": checkpoint,
            "current_points": latest["season_points"],
            "current_gd": latest["season_gd"],
        }
    ).reset_index(drop=True)
    return standings, latest.reset_index(drop=True), remaining


def backtest_season(
    matches: pd.DataFrame,
    season: int,
    checkpoints: tuple[int, ...] = DEFAULT_CHECKPOINTS,
    n_simulations: int = 2000,
    seed: int = 0,
) -> pd.DataFrame:
    """One row per (checkpoint, source, team) with the simulated title probability."""
    champion = final_table(matches[matches["season"] == season]).index[0]
    model, le = train_on_earlier_seasons(matches, season)

    out = []
    for cp in checkpoints:
        standings, live, remaining = state_at_checkpoint(matches, season, cp)
        season_rows = matches[matches["season"] == season]
        played = season_rows[season_rows["matchday"] <= cp]
        teams = standings["team"].tolist()
        idx = {t: i for i, t in enumerate(teams)}
        fixtures = remaining[
            remaining["home_team_name"].isin(idx) & remaining["away_team_name"].isin(idx)
        ]

        history = matches[(matches["season"] < season) | matches.index.isin(played.index)]
        goals_model = PoissonGoalModel().fit(history)
        comps = fixture_components(model, fixtures, live, le, goals_model)
        margins = empirical_margins(history)

        for source, weights in SOURCES.items():
            probs = blend_probs(comps, weights).reshape(-1, 3)
            sim = simulate_title_race(
                fixtures["home_team_name"].map(idx).to_numpy(dtype=int),
                fixtures["away_team_name"].map(idx).to_numpy(dtype=int),
                probs,
                standings["current_points"].to_numpy(dtype=float),
                standings["current_gd"].to_numpy(dtype=float),
                n_simulations,
                seed,
                margins,
            )
            for team, wins in zip(teams, sim["title_counts"]):
                out.append(
                    {
                        "season": season,
                        "checkpoint": cp,
                        "source": source,
                        "team": team,
                        "title_prob": wins / n_simulations,
                        "is_champion": team == champion,
                    }
                )
    return pd.DataFrame(out)


def score_backtest(results: pd.DataFrame) -> pd.DataFrame:
    """Per (season, checkpoint, source): P(champion) and the Brier score of the title distribution."""
    rows = []
    for (season, cp, source), g in results.groupby(["season", "checkpoint", "source"]):
        rows.append(
            {
                "season": season,
                "checkpoint": cp,
                "source": source,
                "p_champion": float(g.loc[g["is_champion"], "title_prob"].sum()),
                "brier": float(((g["title_prob"] - g["is_champion"].astype(float)) ** 2).sum()),
            }
        )
    return pd.DataFrame(rows)
