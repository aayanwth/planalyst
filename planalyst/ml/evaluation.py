"""
PLanalyst — Walk-forward evaluation of the match-outcome model against baselines.

For every test season S the model is trained on seasons < S only, then scored on the
matches of S. Everything is evaluated at match level as [P(home win), P(draw), P(away win)]
so the XGBoost model (which predicts per team) and the baselines are directly comparable.

Compared on the same matches:
  prior          class frequencies of the training seasons (home-advantage baseline)
  elo_formula    Elo expectation incl. home advantage and a fixed draw rate (the Elo half of the blend)
  logit_elo      multinomial logistic regression on the Elo gap (strong simple baseline)
  poisson_glm    independent-Poisson goals model (team attack/defence + home effect)
  xgb_full       production XGBoost features
  xgb_elo_only   XGBoost on Elo + venue only            } feature-group ablations
  xgb_form_only  XGBoost on everything except Elo       }
  blend          equal-weight mix of xgb_full, elo_formula and poisson_glm (what predict.py serves)

Metrics: log loss, ranked probability score (RPS, the standard 1X2 forecast metric: it
respects the home > draw > away ordering), multiclass Brier score and accuracy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import LabelEncoder

from planalyst.ml.elo import outcome_probs_array
from planalyst.ml.features import build_feature_frame
from planalyst.ml.metrics import (  # noqa: F401  (re-exported for callers and tests)
    OUTCOMES,
    brier_per_match,
    calibration_table,
    expected_calibration_error,
    log_loss_per_match,
    outcome_index,
    paired_bootstrap,
    rps_per_match,
    summarize,
)
from planalyst.ml.poisson import PoissonGoalModel
from planalyst.ml.predict import BLEND_WEIGHTS, blend_probs
from planalyst.ml.train import FEATURE_COLUMNS, fit_model, prepare_training_frame

ELO_ONLY_FEATURES = ["elo_rating", "elo_diff", "is_home"]
FORM_ONLY_FEATURES = [c for c in FEATURE_COLUMNS if c not in ("elo_rating", "elo_diff")]
XGB_FEATURE_SETS = {
    "xgb_full": FEATURE_COLUMNS,
    "xgb_elo_only": ELO_ONLY_FEATURES,
    "xgb_form_only": FORM_ONLY_FEATURES,
}
MODEL_ORDER = [
    "prior",
    "elo_formula",
    "logit_elo",
    "poisson_glm",
    "xgb_elo_only",
    "xgb_form_only",
    "xgb_full",
    "blend",
]


# ── Match-level frame ────────────────────────────────────────────────────────
def build_evaluation_frame(matches: pd.DataFrame) -> pd.DataFrame:
    """
    Team-level rows that describe each team's NEXT match (features known before kick-off),
    using exactly the production feature code. `next_id` identifies that match.
    """
    frame = prepare_training_frame(build_feature_frame(matches), matches)
    frame["next_id"] = frame.groupby(["season", "team"])["id"].shift(-1)
    return frame.dropna(subset=FEATURE_COLUMNS + ["next_result", "next_id"])


def make_pairs(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Home-team rows and away-team rows for matches where both are available, index = match id."""
    home = frame[frame["is_home"] == 1].set_index("next_id")
    away = frame[frame["is_home"] == 0].set_index("next_id")
    idx = home.index.intersection(away.index)
    return home.loc[idx].sort_index(), away.loc[idx].sort_index()


def pair_outcomes(home: pd.DataFrame) -> np.ndarray:
    """Outcome index from the home team's perspective (W/D/L -> 0/1/2)."""
    return home["next_result"].map({"W": 0, "D": 1, "L": 2}).to_numpy(dtype=int)


# ── Predictors ───────────────────────────────────────────────────────────────
def prior_probs(train_y: np.ndarray, n: int) -> np.ndarray:
    freq = np.bincount(train_y, minlength=3) / len(train_y)
    return np.tile(freq, (n, 1))


def elo_formula_probs(home: pd.DataFrame, away: pd.DataFrame) -> np.ndarray:
    return outcome_probs_array(home["elo_rating"].to_numpy(), away["elo_rating"].to_numpy())


def poisson_probs(
    train_matches: pd.DataFrame, test_home: pd.DataFrame, test_away: pd.DataFrame
) -> np.ndarray:
    """
    Poisson goals model fitted on earlier matches. The paired rows share an index (the match
    being predicted), so the teams are the home row's `team` and the away row's `team`.
    (Do not use the `opponent` column: it describes the team's previous match.)
    """
    model = PoissonGoalModel().fit(train_matches)
    return model.outcome_probs(test_home["team"], test_away["team"])


def logit_elo_probs(
    train_home: pd.DataFrame,
    train_away: pd.DataFrame,
    test_home: pd.DataFrame,
    test_away: pd.DataFrame,
) -> np.ndarray:
    def gap(h, a):
        return (h["elo_rating"] - a["elo_rating"]).to_numpy().reshape(-1, 1)

    clf = LogisticRegression(max_iter=1000)
    clf.fit(gap(train_home, train_away), pair_outcomes(train_home))
    probs = np.zeros((len(test_home), 3))
    probs[:, clf.classes_] = clf.predict_proba(gap(test_home, test_away))
    return probs


def xgb_match_probs(
    train_home: pd.DataFrame,
    train_away: pd.DataFrame,
    test_home: pd.DataFrame,
    test_away: pd.DataFrame,
    features: list[str],
) -> np.ndarray:
    """Fit the production XGBoost on team rows, then merge each match's two team views."""
    train = pd.concat([train_home, train_away])
    le = LabelEncoder()
    y = le.fit_transform(train["next_result"])
    model = fit_model(train[features].to_numpy(), y)

    order = [list(le.classes_).index(c) for c in "WDL"]
    home_view = model.predict_proba(test_home[features].to_numpy())[:, order]  # W, D, L
    away_view = model.predict_proba(test_away[features].to_numpy())[:, order]
    probs = np.column_stack(
        [
            (home_view[:, 0] + away_view[:, 2]) / 2,
            (home_view[:, 1] + away_view[:, 1]) / 2,
            (home_view[:, 2] + away_view[:, 0]) / 2,
        ]
    )
    return probs / probs.sum(axis=1, keepdims=True)


# ── Walk-forward driver ──────────────────────────────────────────────────────
def walk_forward(
    matches: pd.DataFrame, test_seasons: list[int]
) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    """
    Returns (meta, probs): meta has one row per evaluated match (season, match id, outcome y);
    probs maps each model name to an (N, 3) probability array aligned with meta.
    """
    frame = build_evaluation_frame(matches)
    home_all, away_all = make_pairs(frame)

    metas: list[pd.DataFrame] = []
    chunks: dict[str, list[np.ndarray]] = {m: [] for m in MODEL_ORDER}

    for season in test_seasons:
        tr = (home_all["season"] < season).to_numpy()
        te = (home_all["season"] == season).to_numpy()
        if not tr.any() or not te.any():
            raise ValueError(f"Season {season}: need earlier seasons to train on and its own matches.")
        tr_h, tr_a, te_h, te_a = home_all[tr], away_all[tr], home_all[te], away_all[te]

        y_train, y_test = pair_outcomes(tr_h), pair_outcomes(te_h)
        metas.append(pd.DataFrame({"season": season, "match_id": te_h.index, "y": y_test}))

        chunks["prior"].append(prior_probs(y_train, len(te_h)))
        chunks["elo_formula"].append(elo_formula_probs(te_h, te_a))
        chunks["logit_elo"].append(logit_elo_probs(tr_h, tr_a, te_h, te_a))
        chunks["poisson_glm"].append(poisson_probs(matches[matches["season"] < season], te_h, te_a))
        for name, feats in XGB_FEATURE_SETS.items():
            chunks[name].append(xgb_match_probs(tr_h, tr_a, te_h, te_a, feats))
        chunks["blend"].append(
            blend_probs(
                {
                    "xgb": chunks["xgb_full"][-1],
                    "elo": chunks["elo_formula"][-1],
                    "poisson": chunks["poisson_glm"][-1],
                },
                BLEND_WEIGHTS,
            )
        )

    meta = pd.concat(metas, ignore_index=True)
    probs = {name: np.vstack(parts) for name, parts in chunks.items()}
    return meta, probs
