from sqlalchemy import create_engine, text

from planalyst.config import POSTGRES_CONNECTION_STRING
from planalyst.nlp.sentiment import log_to_mlflow

engine = create_engine(POSTGRES_CONNECTION_STRING)
with engine.connect() as conn:
    conn.execute(text("ALTER TABLE gold.gold_title_predictions ADD COLUMN IF NOT EXISTS model_version TEXT"))
    conn.execute(text("UPDATE gold.gold_title_predictions SET model_version = COALESCE(model_version, 'xgb_v2')"))
    conn.commit()
    rows = conn.execute(text("""
        SELECT article_url, sentiment_label, sentiment_score, model_name
        FROM silver.silver_sentiment_scores
    """)).mappings().all()

scores = [dict(r) for r in rows]
model_name = scores[0]["model_name"] if scores else "unknown"
print(f"Logging {len(scores)} existing sentiment scores to MLflow ({model_name})")
log_to_mlflow(scores, model_name)

print("model_version column ready")
