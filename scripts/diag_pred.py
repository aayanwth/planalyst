from sqlalchemy import create_engine, text
from planalyst.config import POSTGRES_CONNECTION_STRING

e = create_engine(POSTGRES_CONNECTION_STRING)
with e.connect() as c:
    print("=== TITLE PREDICTIONS ===")
    rows = c.execute(text("""
        SELECT team_name, win_probability, avg_final_points, avg_final_rank, matchweek
        FROM gold.gold_title_predictions
        ORDER BY win_probability DESC
    """)).fetchall()
    total = 0
    for r in rows:
        print(tuple(r))
        total += float(r[1])
    print("SUM", round(total, 4), "N", len(rows))

    print("\n=== NEWS DATE RANGE ===")
    print(c.execute(text("""
        SELECT MIN(published_at), MAX(published_at) FROM bronze.raw_news_articles
    """)).fetchall())

    print("\n=== FIXTURES PER MW ===")
    print(c.execute(text("""
        SELECT matchday, COUNT(*) FROM bronze.raw_matches GROUP BY 1
        HAVING COUNT(*) <> 10 ORDER BY 1
    """)).fetchall() or "all matchweeks have 10 fixtures")
