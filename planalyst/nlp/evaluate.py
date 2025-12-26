"""
PLanalyst — Does the sentiment model agree with a human on football headlines?

The scoring model (CardiffNLP RoBERTa, trained on tweets) was never validated on football
news. This module closes that loop in two steps:

  1. Export a random sample of scored articles for a person to label:
         python -m planalyst.nlp.evaluate sample --n 200
     -> data/sentiment_to_label.csv  (fill the empty `label` column with
        POSITIVE / NEUTRAL / NEGATIVE and save as data/sentiment_labelled.csv)

  2. Score the labelled file and report accuracy, per-class precision/recall/F1,
     macro-F1 and the confusion matrix:
         python -m planalyst.nlp.evaluate score data/sentiment_labelled.csv

No labels ship with the repo: accuracy numbers are only meaningful when a human produced them.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

import pandas as pd

from planalyst.config import PROJECT_ROOT

LABELS = ["NEGATIVE", "NEUTRAL", "POSITIVE"]
SAMPLE_PATH = PROJECT_ROOT / "data" / "sentiment_to_label.csv"
REPORT_PATH = PROJECT_ROOT / "docs" / "sentiment_model_eval.md"


def load_labelled(path) -> pd.DataFrame:
    """Read a labelled CSV (columns: text, label) and validate the labels."""
    df = pd.read_csv(path)
    missing = {"text", "label"} - set(df.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")
    df = df.dropna(subset=["text", "label"]).copy()
    df["label"] = df["label"].astype(str).str.strip().str.upper()
    bad = sorted(set(df["label"]) - set(LABELS))
    if bad:
        raise ValueError(f"Unknown labels {bad}; use one of {LABELS}")
    if df.empty:
        raise ValueError("No labelled rows found - fill in the `label` column first.")
    return df.reset_index(drop=True)


def classification_metrics(y_true: list[str], y_pred: list[str]) -> dict:
    """Accuracy, per-class precision/recall/F1/support, macro-F1 and a confusion matrix."""
    from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support

    p, r, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=LABELS, zero_division=0
    )
    return {
        "n": len(y_true),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1.mean()),
        "per_class": {
            label: {
                "precision": float(p[i]),
                "recall": float(r[i]),
                "f1": float(f1[i]),
                "support": int(support[i]),
            }
            for i, label in enumerate(LABELS)
        },
        "confusion": pd.DataFrame(
            confusion_matrix(y_true, y_pred, labels=LABELS),
            index=[f"true {label}" for label in LABELS],
            columns=[f"pred {label}" for label in LABELS],
        ),
    }


def evaluate(df: pd.DataFrame, predict: Callable[[list[str]], list[str]]) -> dict:
    """Run `predict` (texts -> labels) over a labelled frame and score the agreement."""
    preds = predict(df["text"].tolist())
    if len(preds) != len(df):
        raise ValueError("predict() must return one label per text")
    return classification_metrics(df["label"].tolist(), list(preds))


def to_markdown(metrics: dict, model_name: str) -> str:
    rows = "\n".join(
        f"| {label} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | {m['support']} |"
        for label, m in metrics["per_class"].items()
    )
    conf = metrics["confusion"]
    conf_rows = "\n".join(
        f"| {idx} | " + " | ".join(str(v) for v in row) + " |" for idx, row in conf.iterrows()
    )
    return (
        f"# Sentiment model vs human labels\n\n"
        f"Model: `{model_name}` · labelled headlines: {metrics['n']} · "
        f"accuracy: {metrics['accuracy']:.3f} · macro-F1: {metrics['macro_f1']:.3f}\n\n"
        f"| class | precision | recall | F1 | support |\n|---|---|---|---|---|\n{rows}\n\n"
        f"Confusion matrix (rows = human label):\n\n"
        f"| | " + " | ".join(conf.columns) + " |\n|---|" + "---|" * len(conf.columns) + f"\n{conf_rows}\n"
    )


def build_predictor() -> tuple[Callable[[list[str]], list[str]], str]:
    """Wrap the production scorer (same model, truncation and label mapping as the pipeline)."""
    from planalyst.nlp.sentiment import load_sentiment_pipeline, normalize_label

    pipe, model_name = load_sentiment_pipeline()

    def predict(texts: list[str]) -> list[str]:
        return [
            normalize_label(out["label"], model_name)
            for out in pipe([t[:500] for t in texts], batch_size=16)
        ]

    return predict, model_name


def export_sample(n: int, seed: int = 0, path=SAMPLE_PATH) -> int:
    """Write a random sample of Silver headlines (+ the model's current label) to label by hand."""
    from sqlalchemy import create_engine, text

    from planalyst.config import SQLALCHEMY_CONNECTION_STRING

    query = text("""
        SELECT sna.article_url, sna.title, sna.description, sna.team_name
        FROM public_silver.silver_news_articles sna
    """)
    with create_engine(SQLALCHEMY_CONNECTION_STRING).connect() as conn:
        df = pd.read_sql(query, conn)
    df["text"] = (df["title"].fillna("") + " " + df["description"].fillna("")).str.strip()
    df = df[df["text"] != ""].sample(n=min(n, len(df)), random_state=seed)
    out = df[["article_url", "team_name", "text"]].assign(label="")
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    return len(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sample = sub.add_parser("sample", help="export headlines to label")
    sample.add_argument("--n", type=int, default=200)
    score = sub.add_parser("score", help="score a labelled CSV")
    score.add_argument("path")
    args = parser.parse_args()

    if args.command == "sample":
        n = export_sample(args.n)
        print(f"Wrote {n} headlines to {SAMPLE_PATH}. Fill in `label`, then run the `score` command.")
        return

    df = load_labelled(args.path)
    predict, model_name = build_predictor()
    report = to_markdown(evaluate(df, predict), model_name)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
