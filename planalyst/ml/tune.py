"""
PLanalyst — Hyperparameter selection on a validation window.

Selects model settings on validation seasons (default 2018 and 2019, each using only earlier
seasons): Elo parameters, Poisson regularisation, XGBoost configuration and blend weights.
The walk-forward test seasons used in docs/model_evaluation.md (2020+) are never touched here, so the reported test numbers are not tuned on.

Run:  python -m planalyst.ml.tune
"""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder

from planalyst.ml import evaluation as ev
from planalyst.ml.elo import EloParams, outcome_probs_array, run_elo
from planalyst.ml.metrics import log_loss_per_match, outcome_index, rps_per_match
from planalyst.ml.poisson import PoissonGoalModel
from planalyst.ml.train import FEATURE_COLUMNS, fit_model

VALIDATION_SEASONS = (2018, 2019)
LEGACY_PARAMS = {
    "n_estimators": 300,
    "max_depth": 6,
    "learning_rate": 0.08,
    "min_child_weight": 3,
    "gamma": 0.1,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
}
GRID = {
    "max_depth": [2, 3, 4],
    "n_estimators": [100, 200],
    "min_child_weight": [10, 30],
}


def inverse_frequency_weights(y: np.ndarray) -> np.ndarray:
    counts = np.bincount(y, minlength=3)
    return np.array([len(y) / (3 * max(counts[i], 1)) for i in y])


def score_config(home, away, seasons, overrides: dict, weighted: bool) -> dict[str, float]:
    losses, rps = [], []
    for s in seasons:
        tr = (home["season"] < s).to_numpy()
        te = (home["season"] == s).to_numpy()
        train = pd.concat([home[tr], away[tr]])
        le = LabelEncoder()
        y = le.fit_transform(train["next_result"])
        model = fit_model(
            train[FEATURE_COLUMNS].to_numpy(),
            y,
            sample_weight=inverse_frequency_weights(y) if weighted else None,
            **overrides,
        )
        order = [list(le.classes_).index(c) for c in "WDL"]
        hv = model.predict_proba(home[te][FEATURE_COLUMNS].to_numpy())[:, order]
        av = model.predict_proba(away[te][FEATURE_COLUMNS].to_numpy())[:, order]
        p = np.column_stack(
            [(hv[:, 0] + av[:, 2]) / 2, (hv[:, 1] + av[:, 1]) / 2, (hv[:, 2] + av[:, 0]) / 2]
        )
        p /= p.sum(axis=1, keepdims=True)
        y_true = ev.pair_outcomes(home[te])
        losses.append(ev.log_loss_per_match(p, y_true))
        rps.append(ev.rps_per_match(p, y_true))
    return {"log_loss": float(np.concatenate(losses).mean()), "rps": float(np.concatenate(rps).mean())}


ELO_GRID = {
    "home_advantage": [0, 40, 65, 90, 115, 140],
    "season_regression": [0.0, 0.2, 0.33, 0.5],
    "new_team_elo": [1500, 1450, 1400, 1350],
    "draw_prob": [0.20, 0.22, 0.24, 0.26, 0.28],
}


def elo_validation_table(matches: pd.DataFrame, seasons=VALIDATION_SEASONS) -> pd.DataFrame:
    """
    Score Elo-only probabilities on the validation seasons for every parameter combination
    (ratings are replayed from the first season, so only earlier results are ever used).
    """
    ordered = matches.sort_values(["season", "matchday"], kind="stable")
    mask = ordered["season"].isin(seasons).to_numpy()
    y = outcome_index(ordered["score_home"], ordered["score_away"])[mask]
    rows = []
    for ha, reg, new, draw in itertools.product(*ELO_GRID.values()):
        params = EloParams(
            home_advantage=ha, season_regression=reg, new_team_elo=new, draw_prob=draw
        )
        _, pre = run_elo(matches, params)
        probs = outcome_probs_array(pre["home_elo"].to_numpy()[mask], pre["away_elo"].to_numpy()[mask], params)
        rows.append(
            {
                "home_advantage": ha,
                "season_regression": reg,
                "new_team_elo": new,
                "draw_prob": draw,
                "log_loss": float(log_loss_per_match(probs, y).mean()),
                "rps": float(rps_per_match(probs, y).mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("log_loss").reset_index(drop=True)


POISSON_GRID = {
    "alpha": [0.0001, 0.001, 0.003, 0.01, 0.03, 0.1],
    "half_life_seasons": [None, 0.5, 0.75, 1.0, 1.5, 2.0, 4.0],
}


def poisson_validation_table(matches: pd.DataFrame, seasons=VALIDATION_SEASONS) -> pd.DataFrame:
    """Validation log loss of the Poisson goals model for each regularisation / decay setting."""
    home, away = ev.make_pairs(ev.build_evaluation_frame(matches))
    rows = []
    for alpha, half_life in itertools.product(*POISSON_GRID.values()):
        losses, rps = [], []
        for season in seasons:
            te = (home["season"] == season).to_numpy()
            model = PoissonGoalModel(alpha, half_life).fit(matches[matches["season"] < season])
            probs = model.outcome_probs(home[te]["team"], away[te]["team"])
            y = ev.pair_outcomes(home[te])
            losses.append(log_loss_per_match(probs, y))
            rps.append(rps_per_match(probs, y))
        rows.append(
            {
                "alpha": alpha,
                "half_life_seasons": "none" if half_life is None else half_life,
                "log_loss": float(np.concatenate(losses).mean()),
                "rps": float(np.concatenate(rps).mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("log_loss").reset_index(drop=True)


def blend_weight_table(
    matches: pd.DataFrame, seasons=VALIDATION_SEASONS, step: float = 0.1
) -> pd.DataFrame:
    """
    Validation log loss for every (xgb, elo, poisson) weight combination on a coarse simplex
    grid, plus the equal-weight blend that production serves. The table exists to show how flat
    the optimum is: fitting three weights on ~700 matches would mostly fit noise.
    """
    meta, probs = ev.walk_forward(matches, list(seasons))
    y = meta["y"].to_numpy()
    rows = []
    n_steps = round(1 / step)
    for i in range(n_steps + 1):
        for j in range(n_steps + 1 - i):
            w = {"xgb": i * step, "elo": j * step, "poisson": 1 - (i + j) * step}
            mix = sum(w[k] * probs[name] for k, name in
                      (("xgb", "xgb_full"), ("elo", "elo_formula"), ("poisson", "poisson_glm")))
            rows.append(
                {
                    "w_xgb": round(w["xgb"], 2),
                    "w_elo": round(w["elo"], 2),
                    "w_poisson": round(w["poisson"], 2),
                    "log_loss": float(log_loss_per_match(mix, y).mean()),
                    "rps": float(rps_per_match(mix, y).mean()),
                }
            )
    return pd.DataFrame(rows).sort_values("log_loss").reset_index(drop=True)


def validation_table(matches: pd.DataFrame, seasons=VALIDATION_SEASONS) -> pd.DataFrame:
    """One row per candidate config, sorted best-first by validation log loss."""
    home, away = ev.make_pairs(ev.build_evaluation_frame(matches))
    rows = [
        {"config": "legacy (depth 6, 300 trees, class-weighted)", **score_config(home, away, seasons, LEGACY_PARAMS, True)}
    ]
    for depth, n_est, mcw in itertools.product(*GRID.values()):
        overrides = {"max_depth": depth, "n_estimators": n_est, "min_child_weight": mcw}
        rows.append(
            {
                "config": f"depth {depth}, {n_est} trees, min_child_weight {mcw}",
                **score_config(home, away, seasons, overrides, False),
            }
        )
    rows.append(
        {
            "config": "production params + class weights",
            **score_config(home, away, seasons, {}, True),
        }
    )
    rows.append({"config": "production params (no class weights)", **score_config(home, away, seasons, {}, False)})

    logit = []
    for s in seasons:
        tr = (home["season"] < s).to_numpy()
        te = (home["season"] == s).to_numpy()
        p = ev.logit_elo_probs(home[tr], away[tr], home[te], away[te])
        y = ev.pair_outcomes(home[te])
        logit.append((ev.log_loss_per_match(p, y), ev.rps_per_match(p, y)))
    rows.append(
        {
            "config": "reference: logistic regression on Elo gap",
            "log_loss": float(np.concatenate([x[0] for x in logit]).mean()),
            "rps": float(np.concatenate([x[1] for x in logit]).mean()),
        }
    )
    return pd.DataFrame(rows).sort_values("log_loss").reset_index(drop=True)


if __name__ == "__main__":
    from planalyst.ml.offline_data import load_matches

    data = load_matches(list(range(2015, 2026)))
    fmt = {"float_format": lambda v: f"{v:.4f}"}
    print("== Elo parameters (top 8 of the grid) ==")
    print(elo_validation_table(data).head(8).to_string(index=False, **fmt))
    print("\n== Poisson goals model (top 8) ==")
    print(poisson_validation_table(data).head(8).to_string(index=False, **fmt))
    print("\n== XGBoost configurations ==")
    print(validation_table(data).to_string(index=False, **fmt))
    print("\n== Blend weights (top 8) ==")
    print(blend_weight_table(data).head(8).to_string(index=False, **fmt))
