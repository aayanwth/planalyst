from sqlalchemy import create_engine, text
from planalyst.config import POSTGRES_CONNECTION_STRING

e = create_engine(POSTGRES_CONNECTION_STRING)
with e.connect() as c:
    rows = c.execute(text("""
        SELECT team_name, result, points, avg_sentiment_score, article_count, cumulative_points
        FROM public_gold.fact_team_sentiment_performance
        ORDER BY cumulative_points DESC, cumulative_gd DESC
    """)).fetchall()
    print("FACT MW1:")
    for r in rows:
        print(tuple(r))
    n = c.execute(text("SELECT SUM(article_count) FROM public_gold.fact_team_sentiment_performance")).scalar()
    print("TOTAL ARTICLES IN FACT", n)
