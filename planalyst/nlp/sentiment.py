"""
PLanalyst — NLP Sentiment Scoring

Runs Hugging Face sentiment analysis on news articles from the Silver layer.
Writes results to silver.silver_sentiment_scores.
Logs each scoring run to MLflow.
"""

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import create_engine, text

from planalyst.config import SQLALCHEMY_CONNECTION_STRING

# ── Model Configuration ─────────────────────────────────────────────────────
# Primary model: CardiffNLP twitter-roberta-base for sentiment
# Falls back to distilbert-base-uncased-finetuned-sst-2 if unavailable
PRIMARY_MODEL = "cardiffnlp/twitter-roberta-base-sentiment-latest"
FALLBACK_MODEL = "distilbert-base-uncased-finetuned-sst-2-english"

# Label mapping for CardiffNLP model (outputs LABEL_0, LABEL_1, LABEL_2)
CARDIFFNLP_LABEL_MAP = {
    "LABEL_0": "NEGATIVE",
    "LABEL_1": "NEUTRAL",
    "LABEL_2": "POSITIVE",
    "negative": "NEGATIVE",
    "neutral": "NEUTRAL",
    "positive": "POSITIVE",
    "NEGATIVE": "NEGATIVE",
    "NEUTRAL": "NEUTRAL",
    "POSITIVE": "POSITIVE",
}

# Label mapping for distilbert SST-2 (binary sentiment)
SST2_LABEL_MAP = {
    "POSITIVE": "POSITIVE",
    "NEGATIVE": "NEGATIVE",
    "LABEL_0": "NEGATIVE",
    "LABEL_1": "POSITIVE",
}


def load_sentiment_pipeline(model_name: str = PRIMARY_MODEL):
    """Load a HuggingFace sentiment analysis pipeline."""
    from transformers import pipeline

    try:
        print(f"  Loading model: {model_name}")
        sentiment_pipeline = pipeline(
            "sentiment-analysis",
            model=model_name,
            tokenizer=model_name,
            max_length=512,
            truncation=True,
        )
        return sentiment_pipeline, model_name
    except Exception as e:
        print(f"  Warning: Could not load {model_name}: {e}")
        if model_name != FALLBACK_MODEL:
            print(f"  Falling back to: {FALLBACK_MODEL}")
            return load_sentiment_pipeline(FALLBACK_MODEL)
        raise


def normalize_label(label: str, model_name: str) -> str:
    """Map model-specific label to standardized POSITIVE/NEUTRAL/NEGATIVE."""
    if model_name == PRIMARY_MODEL or "cardiffnlp" in model_name:
        return CARDIFFNLP_LABEL_MAP.get(label, label.upper())
    else:
        return SST2_LABEL_MAP.get(label, label.upper())


def fetch_unscored_articles(engine) -> pd.DataFrame:
    """Fetch articles from silver_news_articles that haven't been scored yet."""
    query = text("""
        SELECT sna.article_url, sna.title, sna.description, sna.content, sna.team_name
        FROM public_silver.silver_news_articles sna
        LEFT JOIN silver.silver_sentiment_scores ss
            ON sna.article_url = ss.article_url
        WHERE ss.article_url IS NULL
    """)

    with engine.connect() as conn:
        result = conn.execute(query)
        rows = result.fetchall()
        columns = result.keys()

    return pd.DataFrame(rows, columns=columns)


def prepare_text_for_scoring(row) -> str:
    """Prepare article text for sentiment analysis. Prefer title + description."""
    parts = []
    # DataFrame rows carry NULLs as NaN (truthy), so test with isna rather than truthiness;
    # otherwise the literal word "nan" ends up in the text sent to the model.
    for field in ("title", "description"):
        value = row.get(field)
        if value is not None and not pd.isna(value) and str(value).strip():
            parts.append(str(value))

    text = " ".join(parts).strip()

    # Truncate to avoid model max length issues
    if len(text) > 500:
        text = text[:500]

    return text


def score_articles(articles_df: pd.DataFrame, sentiment_pipeline, model_name: str) -> list[dict]:
    """
    Score a DataFrame of articles using the sentiment pipeline.
    Returns a list of dicts ready for DB insertion.
    """
    results = []
    # Skip articles with no title/description rather than scoring placeholder text
    texts = [prepare_text_for_scoring(row) for _, row in articles_df.iterrows()]
    keep = [bool(t) for t in texts]
    articles_df = articles_df[keep]
    texts = [t for t in texts if t]

    if not texts:
        return results

    # Batch score
    print(f"  Scoring {len(texts)} articles...")
    predictions = sentiment_pipeline(texts, batch_size=16)

    scored_at = datetime.now(timezone.utc).isoformat()

    for i, (pred, (_, row)) in enumerate(zip(predictions, articles_df.iterrows())):
        label = normalize_label(pred["label"], model_name)
        score = round(pred["score"], 4)

        results.append({
            "article_url": row["article_url"],
            "sentiment_label": label,
            "sentiment_score": score,
            "model_name": model_name,
            "scored_at": scored_at,
        })

    return results


CREATE_SCORES_TABLE_SQL = text("""
    CREATE TABLE IF NOT EXISTS silver.silver_sentiment_scores (
        article_url TEXT PRIMARY KEY,
        sentiment_label TEXT NOT NULL,
        sentiment_score FLOAT NOT NULL,
        model_name TEXT NOT NULL,
        scored_at TIMESTAMP NOT NULL
    )
""")


def ensure_scores_table(engine=None) -> None:
    """Create silver.silver_sentiment_scores if missing (dbt's gold fact joins on it)."""
    engine = engine or create_engine(SQLALCHEMY_CONNECTION_STRING)
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS silver"))
        conn.execute(CREATE_SCORES_TABLE_SQL)


def write_scores_to_db(scores: list[dict], engine) -> None:
    """Write sentiment scores to the silver.silver_sentiment_scores table."""
    if not scores:
        print("  No scores to write.")
        return

    create_table_sql = CREATE_SCORES_TABLE_SQL

    insert_sql = text("""
        INSERT INTO silver.silver_sentiment_scores
            (article_url, sentiment_label, sentiment_score, model_name, scored_at)
        VALUES
            (:article_url, :sentiment_label, :sentiment_score, :model_name, :scored_at)
        ON CONFLICT (article_url) DO UPDATE SET
            sentiment_label = EXCLUDED.sentiment_label,
            sentiment_score = EXCLUDED.sentiment_score,
            model_name = EXCLUDED.model_name,
            scored_at = EXCLUDED.scored_at
    """)

    with engine.begin() as conn:
        conn.execute(create_table_sql)
        for score in scores:
            conn.execute(insert_sql, score)

    print(f"  Wrote {len(scores)} sentiment scores to silver.silver_sentiment_scores")


def log_to_mlflow(scores: list[dict], model_name: str) -> None:
    """Log the sentiment scoring run to MLflow."""
    try:
        from planalyst.tracking import configure_mlflow

        mlflow = configure_mlflow()
        mlflow.set_experiment("planalyst_sentiment_scoring")

        with mlflow.start_run(run_name=f"sentiment_scoring_{datetime.now().strftime('%Y%m%d_%H%M')}"):
            mlflow.log_param("model_name", model_name)
            mlflow.log_param("dataset_size", len(scores))

            if scores:
                # Compute summary stats
                pos = sum(1 for s in scores if s["sentiment_label"] == "POSITIVE")
                neg = sum(1 for s in scores if s["sentiment_label"] == "NEGATIVE")
                neu = sum(1 for s in scores if s["sentiment_label"] == "NEUTRAL")
                avg_score = sum(s["sentiment_score"] for s in scores) / len(scores)

                mlflow.log_metric("avg_confidence_score", round(avg_score, 4))
                mlflow.log_metric("positive_count", pos)
                mlflow.log_metric("negative_count", neg)
                mlflow.log_metric("neutral_count", neu)
                mlflow.log_metric("total_articles", len(scores))

                print(f"  MLflow logged: {len(scores)} articles, avg_score={avg_score:.4f}")
                print(f"    Positive: {pos}, Negative: {neg}, Neutral: {neu}")

    except Exception as e:
        print(f"  Warning: MLflow logging failed (non-fatal): {e}")
        print("  Sentiment scores were still saved to the database.")


def run_sentiment_scoring() -> list[dict]:
    """
    Main entry point: fetch unscored articles, score them, write to DB, log to MLflow.
    Returns the list of scored results for inspection.
    """
    print("\n[NLP] Starting sentiment scoring pipeline...")

    engine = create_engine(SQLALCHEMY_CONNECTION_STRING)

    # Fetch articles that need scoring
    articles_df = fetch_unscored_articles(engine)
    print(f"  Found {len(articles_df)} unscored articles")

    if articles_df.empty:
        print("  No articles to score. Done.")
        return []

    # Load model
    sentiment_pipeline, model_name = load_sentiment_pipeline()

    # Score
    scores = score_articles(articles_df, sentiment_pipeline, model_name)

    # Write to DB
    write_scores_to_db(scores, engine)

    # Log to MLflow
    log_to_mlflow(scores, model_name)

    # Print sample for checkpoint verification
    print("\n  --- Sample of 10 scored articles ---")
    for s in scores[:10]:
        print(f"    [{s['sentiment_label']:>8}] ({s['sentiment_score']:.3f}) {s['article_url'][:80]}")

    return scores


if __name__ == "__main__":
    run_sentiment_scoring()
