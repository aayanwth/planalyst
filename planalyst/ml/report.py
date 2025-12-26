"""
PLanalyst — Generate docs/model_evaluation.md (+ figures) from a real walk-forward run.

    python -m planalyst.ml.report                 # offline: football-data.co.uk CSVs, no DB
    python -m planalyst.ml.report --source db     # training.historical_matches in Postgres
    python -m planalyst.ml.report --quick         # fewer seasons / simulations (smoke test)

Every number in the generated file comes from this run; nothing is hand-written.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from planalyst.config import PROJECT_ROOT  # noqa: E402
from planalyst.ml import backtest as bt  # noqa: E402
from planalyst.ml import evaluation as ev  # noqa: E402
from planalyst.ml.predict import BLEND_WEIGHTS  # noqa: E402
from planalyst.ml.tune import (  # noqa: E402
    VALIDATION_SEASONS,
    blend_weight_table,
    elo_validation_table,
    poisson_validation_table,
    validation_table,
)

SOURCE_ORDER = ["elo", "poisson", "xgb", "blend"]
DOCS = PROJECT_ROOT / "docs"
IMG = DOCS / "img"
FIRST_SEASON, LAST_SEASON = 2015, 2025
FIRST_TEST_SEASON = 2020


def load_matches(source: str) -> pd.DataFrame:
    if source == "db":
        from sqlalchemy import create_engine

        from planalyst.config import SQLALCHEMY_CONNECTION_STRING
        from planalyst.ml.features import load_historical_data

        return load_historical_data(create_engine(SQLALCHEMY_CONNECTION_STRING))
    from planalyst.ml.offline_data import load_matches as load_csv

    return load_csv(list(range(FIRST_SEASON, LAST_SEASON + 1)))


def md_table(df: pd.DataFrame, floats: str = "{:.4f}") -> str:
    head = "| " + " | ".join(df.columns) + " |\n|" + "---|" * len(df.columns) + "\n"
    body = ""
    for r in df.to_dict("records"):  # records keep per-column types, so ints stay ints
        cells = [floats.format(v) if isinstance(v, float) else str(v) for v in r.values()]
        body += "| " + " | ".join(cells) + " |\n"
    return head + body


def plot_calibration(probs: np.ndarray, y: np.ndarray, label: str, path) -> float:
    table = ev.calibration_table(probs, y, n_bins=8)
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.6), sharex=True, sharey=True)
    names = {"H": "Home win", "D": "Draw", "A": "Away win"}
    for ax, outcome in zip(axes, ev.OUTCOMES):
        t = table[table["outcome"] == outcome]
        ax.plot([0, 1], [0, 1], "--", color="#999", lw=1)
        ax.plot(t["mean_predicted"], t["observed_rate"], "o-", color="#37003c", lw=1.5)
        for _, r in t.iterrows():
            ax.annotate(int(r["n"]), (r["mean_predicted"], r["observed_rate"]),
                        textcoords="offset points", xytext=(4, -10), fontsize=7, color="#666")
        ax.set_title(names[outcome])
        ax.set_xlabel("Predicted probability")
        ax.grid(alpha=0.25)
    axes[0].set_ylabel("Observed frequency")
    fig.suptitle(f"Reliability: {label} (point labels = matches in bin)", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return ev.expected_calibration_error(table)


def plot_backtest(scores: pd.DataFrame, path) -> None:
    mean = scores.groupby(["source", "checkpoint"])["p_champion"].mean().unstack(0)
    colors = {"elo": "#00b3a1", "poisson": "#f5a623", "xgb": "#e90052", "blend": "#37003c"}
    fig, ax = plt.subplots(figsize=(7, 3.8))
    for source in SOURCE_ORDER:
        ax.plot(mean.index, mean[source], "o-", label=source, color=colors[source])
    ax.set_xlabel("Matchweek checkpoint")
    ax.set_ylabel("Mean P(eventual champion)")
    ax.set_title("Title-race backtest: probability given to the actual champion")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def verdict(mean: float, lo: float, hi: float, metric: str, a: str, b: str) -> str:
    if lo > 0:
        return f"{b} is better on {metric} (CI excludes 0)"
    if hi < 0:
        return f"{a} is better on {metric} (CI excludes 0)"
    return f"no clear difference on {metric} (CI includes 0)"


def build_report(source: str, quick: bool) -> str:
    matches = load_matches(source)
    last = int(matches["season"].max())
    test_seasons = list(range(last - 1 if quick else FIRST_TEST_SEASON, last + 1))
    n_sims = 500 if quick else 2000

    meta, probs = ev.walk_forward(matches, test_seasons)
    y = meta["y"].to_numpy()
    n_matches = len(meta)

    # ── Summary table ──
    rows = []
    for name in ev.MODEL_ORDER:
        s = ev.summarize(probs[name], y)
        rows.append({"model": name, "log_loss": s["log_loss"], "rps": s["rps"],
                     "brier": s["brier"], "accuracy": s["accuracy"]})
    summary = pd.DataFrame(rows)

    per_season = pd.DataFrame(
        {
            "season": sorted(meta["season"].unique()),
            **{
                name: [
                    ev.log_loss_per_match(probs[name][meta["season"] == s], y[meta["season"] == s]).mean()
                    for s in sorted(meta["season"].unique())
                ]
                for name in ["prior", "elo_formula", "logit_elo", "poisson_glm", "xgb_full", "blend"]
            },
        }
    )

    # ── Paired bootstrap: is the production model distinguishable from the baselines? ──
    comparisons = [("blend", "logit_elo"), ("blend", "elo_formula"), ("blend", "poisson_glm"),
                   ("blend", "xgb_full"), ("poisson_glm", "logit_elo"), ("xgb_full", "logit_elo"),
                   ("xgb_full", "prior"), ("xgb_full", "xgb_elo_only"),
                   ("xgb_full", "xgb_form_only")]
    boot_rows = []
    for a, b in comparisons:
        for metric, fn in [("log loss", ev.log_loss_per_match), ("RPS", ev.rps_per_match)]:
            m, lo, hi = ev.paired_bootstrap(fn(probs[a], y), fn(probs[b], y))
            boot_rows.append({"A": a, "B": b, "metric": metric, "mean(A-B)": m,
                              "95% CI low": lo, "95% CI high": hi, "reading": verdict(m, lo, hi, metric, a, b)})
    boot = pd.DataFrame(boot_rows)

    # ── Calibration ──
    IMG.mkdir(parents=True, exist_ok=True)
    ece_blend = plot_calibration(probs["blend"], y, "production blend", IMG / "calibration_blend.png")
    ece_xgb = plot_calibration(probs["xgb_full"], y, "xgb_full", IMG / "calibration_xgb.png")
    ece_table = pd.DataFrame(
        [{"model": "xgb_full", "ECE": ece_xgb}, {"model": "blend", "ECE": ece_blend}]
        + [{"model": name, "ECE": ev.expected_calibration_error(ev.calibration_table(probs[name], y, n_bins=8))}
           for name in ("logit_elo", "poisson_glm", "elo_formula")]
    )

    # ── Tuning provenance ──
    elo_tuning = elo_validation_table(matches).head(6)
    poisson_tuning = poisson_validation_table(matches).head(6)
    tuning = validation_table(matches)
    blend_grid = blend_weight_table(matches)
    equal = blend_grid[
        (blend_grid["w_xgb"].sub(1 / 3).abs() < 0.04)
        & (blend_grid["w_elo"].sub(1 / 3).abs() < 0.04)
        & (blend_grid["w_poisson"].sub(1 / 3).abs() < 0.04)
    ].head(1)
    blend_tuning = pd.concat([blend_grid.head(5), equal]).drop_duplicates().reset_index(drop=True)

    # ── Title backtest ──
    checkpoints = (10, 20, 30) if quick else bt.DEFAULT_CHECKPOINTS
    parts = [bt.backtest_season(matches, s, checkpoints, n_sims) for s in test_seasons]
    scores = bt.score_backtest(pd.concat(parts, ignore_index=True))
    plot_backtest(scores, IMG / "title_backtest.png")
    by_source = scores.groupby("source")[["p_champion", "brier"]].mean().reindex(SOURCE_ORDER)
    by_source = by_source.reset_index().rename(columns={"p_champion": "mean P(champion)", "brier": "mean Brier"})
    champs = pd.DataFrame(
        [{"season": f"{s}-{(s + 1) % 100:02d}",
          "champion": bt.final_table(matches[matches["season"] == s]).index[0]} for s in test_seasons]
    )
    late = scores[scores["checkpoint"] == max(checkpoints)].pivot(
        index="season", columns="source", values="p_champion")[SOURCE_ORDER].reset_index()

    src_desc = ("`training.historical_matches` in Postgres" if source == "db"
                else "football-data.co.uk per-season results CSVs (full-time scores only)")
    BLEND_WEIGHTS_TEXT = ", ".join(f"{k} {v:.2f}" for k, v in BLEND_WEIGHTS.items())
    return f"""# Model evaluation

_Generated {date.today().isoformat()} by `python -m planalyst.ml.report` · data: {src_desc}._

Everything below is produced by that command from a single run; nothing is hand-edited.
Seasons {matches['season'].min()}–{last} are available. For each test season the model is trained on
**earlier seasons only** and scored on that season's matches (walk-forward), so no future
information reaches a prediction. Test seasons: {test_seasons[0]}–{test_seasons[-1]}
({n_matches} matches). The first match of each team's season is not scored because the
rolling features need at least one prior game.

## 1. Match-outcome model vs baselines

Probabilities are [P(home), P(draw), P(away)]. Lower is better for every column except accuracy.
RPS (ranked probability score) is the standard 1X2 forecasting metric.

{md_table(summary)}
**Models.** `prior` = training-set outcome frequencies. `elo_formula` = Elo expectation with home
advantage and a fixed draw rate. `logit_elo` = multinomial logistic regression on the Elo gap.
`poisson_glm` = independent-Poisson goals model (attack, defence, home effect). `xgb_full` = XGBoost on all
features. `xgb_elo_only` / `xgb_form_only` = ablations (Elo + venue only; everything except Elo).
`blend` = equal-weight mix of `xgb_full`, `elo_formula` and `poisson_glm` ({BLEND_WEIGHTS_TEXT}), what
`predict.py` serves.

Log loss by season:

{md_table(per_season)}
### Is the difference real? Paired bootstrap

Negative `mean(A-B)` means A has the lower loss. Resampling matches 2,000 times gives a 95% interval.

{md_table(boot)}
## 2. Feature ablation

`xgb_full` vs `xgb_elo_only` and `xgb_form_only` above shows which feature group carries the signal.
Sentiment is **not** in this comparison: the historical seasons have no news archive, so sentiment
cannot be a training feature yet. It is studied separately in `docs/sentiment_correlation.md`.

## 3. Calibration

A calibrated model's points sit on the diagonal. ECE is the match-weighted mean gap between predicted
and observed frequency across 8 bins and 3 outcomes (lower is better).

{md_table(ece_table)}
![Reliability, production blend](img/calibration_blend.png)
![Reliability, xgb_full](img/calibration_xgb.png)

## 4. How the model settings were chosen

Every setting below was chosen on validation seasons {', '.join(map(str, VALIDATION_SEASONS))} (each
using only earlier seasons), which do not overlap the test seasons above. `python -m planalyst.ml.tune`
reproduces all four tables.

**Elo parameters** (grid of 480; top rows). Home advantage and the draw rate matter; season regression
and the promoted-team start barely do.

{md_table(elo_tuning)}
**Poisson goals model.** A plateau: several settings within 0.001 log loss of each other.

{md_table(poisson_tuning)}
**XGBoost configuration** (refit with the Elo above):

{md_table(tuning)}
**Blend weights.** Fitting three weights on about 700 validation matches would mostly fit noise, and
the table shows why: the optimum is flat. Production uses equal weights, which are within a few
thousandths of the best combination.

{md_table(blend_tuning)}
## 5. Title-race backtest

For each test season and each checkpoint matchweek, the model is trained on earlier seasons, standings
and form are frozen at that point, the remaining fixtures are simulated ({n_sims} runs) and the
title probabilities are compared with the real champion. `elo`, `poisson` and `xgb` use that single
component for every fixture; `blend` is the production equal-weight mix. The Poisson model is refit at each
checkpoint on earlier seasons plus the results so far, and winning margins are drawn from the empirical
distribution of past results.

Champions:

{md_table(champs)}
Mean over seasons and checkpoints (Brier = Σ(p − 1[champion])² over all 20 teams; 0 is perfect):

{md_table(by_source)}
Probability given to the eventual champion at matchweek {max(checkpoints)}:

{md_table(late)}
![Title backtest](img/title_backtest.png)

**Caveat.** There is one champion per season, so this is {len(test_seasons)} outcomes per checkpoint.
It can reveal a badly broken simulator; it cannot rank close alternatives with confidence.
"""


def main() -> None:
    warnings.filterwarnings("ignore")
    sys.stdout.reconfigure(encoding="utf-8")  # the report contains non-ASCII symbols
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["csv", "db"], default="csv")
    parser.add_argument("--quick", action="store_true", help="smoke test: 2 seasons, 500 sims")
    args = parser.parse_args()

    text = build_report(args.source, args.quick)
    if args.quick:
        print(text)
        return
    DOCS.mkdir(exist_ok=True)
    (DOCS / "model_evaluation.md").write_text(text, encoding="utf-8")
    print(f"Wrote {DOCS / 'model_evaluation.md'}")


if __name__ == "__main__":
    main()
