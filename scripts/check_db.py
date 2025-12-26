from sqlalchemy import create_engine, text

from planalyst.config import SQLALCHEMY_CONNECTION_STRING

e = create_engine(SQLALCHEMY_CONNECTION_STRING)
with e.connect() as c:
    print("=== pgvector ===")
    print(c.execute(text("SELECT extname, extversion FROM pg_extension WHERE extname='vector'")).fetchall())

    print("\n=== TABLES ===")
    rows = c.execute(text("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema IN ('bronze','silver','gold','training','public_silver','public_gold','public')
          AND table_type = 'BASE TABLE' OR (table_schema IN ('public_silver','public_gold') AND table_type='VIEW')
        ORDER BY 1,2
    """)).fetchall()
    for r in rows:
        print(tuple(r))

    print("\n=== COUNTS ===")
    tables = [
        "bronze.raw_matches",
        "bronze.raw_news_articles",
        "training.historical_matches",
        "training.training_features",
        "public_silver.silver_matches",
        "public_silver.silver_news_articles",
        "public_gold.fact_team_sentiment_performance",
        "public_gold.dim_team",
        "public_gold.dim_matchweek",
        "silver.silver_sentiment_scores",
        "gold.gold_title_predictions",
    ]
    for t in tables:
        try:
            n = c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
            print(t, n)
        except Exception as ex:
            print(t, "ERR", type(ex).__name__, str(ex).split("\n")[0])
            c.rollback()

    print("\n=== LIVE SEASONS ===")
    try:
        print("bronze seasons", c.execute(text("SELECT DISTINCT season FROM bronze.raw_matches ORDER BY 1")).fetchall())
        print("mw1 matches", c.execute(text("SELECT COUNT(*) FROM bronze.raw_matches WHERE matchday=1")).scalar())
        print("mw1 finished", c.execute(text("SELECT COUNT(*) FROM bronze.raw_matches WHERE matchday=1 AND status='FINISHED'")).scalar())
        print("teams home+away", c.execute(text("""
            SELECT COUNT(DISTINCT team) FROM (
              SELECT home_team_name AS team FROM bronze.raw_matches
              UNION SELECT away_team_name FROM bronze.raw_matches
            ) t
        """)).scalar())
    except Exception as ex:
        print("live season err", ex)
        c.rollback()

    print("\n=== TRAINING OVERLAP ===")
    try:
        print("training seasons", c.execute(text("SELECT season, COUNT(*) FROM training.historical_matches GROUP BY season ORDER BY 1")).fetchall())
        print("training has 2026", c.execute(text("SELECT COUNT(*) FROM training.historical_matches WHERE season=2026")).scalar())
        print("bronze has <2026", c.execute(text("SELECT COUNT(*) FROM bronze.raw_matches WHERE season<>2026")).scalar())
    except Exception as ex:
        print("overlap err", ex)
        c.rollback()

    print("\n=== GOLD MW1 COVERAGE ===")
    try:
        print("mw1 teams", c.execute(text("""
            SELECT COUNT(DISTINCT team_name), COUNT(*)
            FROM public_gold.fact_team_sentiment_performance
            WHERE matchweek_number=1
        """)).fetchone())
        print("fact sample", c.execute(text("""
            SELECT team_name, matchweek_number, result, points, avg_sentiment_score, article_count
            FROM public_gold.fact_team_sentiment_performance
            WHERE matchweek_number=1
            ORDER BY team_name
            LIMIT 5
        """)).fetchall())
        print("sentiment counts", c.execute(text("""
            SELECT sentiment_label, COUNT(*) FROM silver.silver_sentiment_scores GROUP BY 1
        """)).fetchall())
    except Exception as ex:
        print("gold err", ex)
        c.rollback()
