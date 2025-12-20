from sqlalchemy import create_engine, text
from planalyst.config import SQLALCHEMY_CONNECTION_STRING

e = create_engine(SQLALCHEMY_CONNECTION_STRING)
with e.connect() as c:
    rows = c.execute(text("""
        SELECT sentiment_label, COUNT(*)
        FROM silver.silver_sentiment_scores
        GROUP BY 1
    """)).fetchall()
    print("LABELS", rows)
    sample = c.execute(text("""
        SELECT ss.sentiment_label, ss.sentiment_score, sna.title, sna.team_name
        FROM silver.silver_sentiment_scores ss
        JOIN public_silver.silver_news_articles sna ON sna.article_url = ss.article_url
        ORDER BY ss.sentiment_score DESC
        LIMIT 10
    """)).fetchall()
    print("TOP CONFIDENCE:")
    for r in sample:
        print(tuple(r))
