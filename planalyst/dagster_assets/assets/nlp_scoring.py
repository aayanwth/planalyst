"""
PLanalyst — Dagster: Asset Definition for NLP Sentiment Scoring

Runs HuggingFace sentiment analysis on unscored articles.
"""

from dagster import AssetExecutionContext, MetadataValue, Output, asset


@asset(
    group_name="silver",
    description="Run NLP sentiment scoring on news articles using HuggingFace",
    deps=["dbt_transformations"],
    kinds={"python", "huggingface", "mlflow"},
)
def nlp_sentiment_scoring(context: AssetExecutionContext) -> Output:
    """Score news articles with sentiment analysis."""
    from planalyst.nlp.sentiment import run_sentiment_scoring

    context.log.info("Starting NLP sentiment scoring...")
    scores = run_sentiment_scoring()
    context.log.info(f"Scored {len(scores)} articles")

    # Summary stats
    if scores:
        pos = sum(1 for s in scores if s["sentiment_label"] == "POSITIVE")
        neg = sum(1 for s in scores if s["sentiment_label"] == "NEGATIVE")
        neu = sum(1 for s in scores if s["sentiment_label"] == "NEUTRAL")
    else:
        pos = neg = neu = 0

    return Output(
        value=len(scores),
        metadata={
            "articles_scored": MetadataValue.int(len(scores)),
            "positive": MetadataValue.int(pos),
            "negative": MetadataValue.int(neg),
            "neutral": MetadataValue.int(neu),
        },
    )
