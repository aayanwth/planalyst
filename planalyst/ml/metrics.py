"""
PLanalyst — Forecast metrics for 1X2 (home / draw / away) probabilities.

Pure numpy/pandas on purpose: the API image uses these for the live accuracy tracker and does
not install scikit-learn or xgboost.

Outcomes are indexed 0 = home win, 1 = draw, 2 = away win. Lower is better for every metric
except accuracy.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

OUTCOMES = ["H", "D", "A"]
EPS = 1e-15


def outcome_index(score_home, score_away) -> np.ndarray:
    """0 = home win, 1 = draw, 2 = away win."""
    sh, sa = np.asarray(score_home), np.asarray(score_away)
    return np.where(sh > sa, 0, np.where(sh == sa, 1, 2))


def log_loss_per_match(probs: np.ndarray, y: np.ndarray) -> np.ndarray:
    return -np.log(np.clip(probs[np.arange(len(y)), y], EPS, 1.0))


def rps_per_match(probs: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Ranked probability score for ordered outcomes (home, draw, away); lower is better."""
    onehot = np.eye(3)[y]
    cum_diff = np.cumsum(probs, axis=1) - np.cumsum(onehot, axis=1)
    return (cum_diff[:, :2] ** 2).sum(axis=1) / 2


def brier_per_match(probs: np.ndarray, y: np.ndarray) -> np.ndarray:
    return ((probs - np.eye(3)[y]) ** 2).sum(axis=1)


def summarize(probs: np.ndarray, y: np.ndarray) -> dict[str, float]:
    return {
        "n": int(len(y)),
        "log_loss": float(log_loss_per_match(probs, y).mean()),
        "rps": float(rps_per_match(probs, y).mean()),
        "brier": float(brier_per_match(probs, y).mean()),
        "accuracy": float((probs.argmax(axis=1) == y).mean()),
    }


def calibration_table(probs: np.ndarray, y: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    """Reliability data: for each outcome, bin the predicted probability and compare to the hit rate."""
    edges = np.linspace(0, 1, n_bins + 1)
    rows = []
    for k, name in enumerate(OUTCOMES):
        p = probs[:, k]
        hit = (y == k).astype(float)
        which = np.clip(np.digitize(p, edges[1:-1]), 0, n_bins - 1)
        for b in range(n_bins):
            mask = which == b
            if mask.any():
                rows.append(
                    {
                        "outcome": name,
                        "bin_low": edges[b],
                        "bin_high": edges[b + 1],
                        "n": int(mask.sum()),
                        "mean_predicted": float(p[mask].mean()),
                        "observed_rate": float(hit[mask].mean()),
                    }
                )
    return pd.DataFrame(rows)


def expected_calibration_error(table: pd.DataFrame) -> float:
    """n-weighted mean |predicted - observed| across all bins and outcomes."""
    gap = (table["mean_predicted"] - table["observed_rate"]).abs()
    return float((gap * table["n"]).sum() / table["n"].sum())


def paired_bootstrap(
    loss_a: np.ndarray, loss_b: np.ndarray, n_boot: int = 2000, seed: int = 0
) -> tuple[float, float, float]:
    """Mean of (loss_a - loss_b) with a 95% percentile bootstrap CI. Negative favours a."""
    diff = np.asarray(loss_a) - np.asarray(loss_b)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(diff), size=(n_boot, len(diff)))
    means = diff[idx].mean(axis=1)
    return float(diff.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))
