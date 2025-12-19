"""
PLanalyst — FastAPI Router: Matchweek endpoints

GET /matchweek/{n}/summary — league-wide sentiment vs results for matchweek N
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from planalyst.api.database import engine

router = APIRouter()


@router.get("/{matchweek_number}/summary")
def get_matchweek_summary(matchweek_number: int):
    """Get league-wide summary: sentiment vs results for a given matchweek."""
    query = text("""
        SELECT
            f.team_name, f.matchweek_number,
            f.result, f.goals_for, f.goals_against, f.points,
            f.avg_sentiment_score, f.article_count,
            f.cumulative_points, f.cumulative_gd,
            d.short_name, d.crest_url, d.tla
        FROM public_gold.fact_team_sentiment_performance f
        JOIN public_gold.dim_team d ON f.team_name = d.team_name
        WHERE f.matchweek_number = :mw
        ORDER BY f.cumulative_points DESC, f.cumulative_gd DESC
    """)
    with engine.connect() as conn:
        rows = conn.execute(query, {"mw": matchweek_number}).mappings().all()

    if not rows:
        raise HTTPException(status_code=404, detail=f"Matchweek {matchweek_number} not found")

    # Compute aggregates
    total_goals = sum(r["goals_for"] for r in rows)
    avg_sentiment = sum(r["avg_sentiment_score"] for r in rows) / len(rows)
    total_articles = sum(r["article_count"] for r in rows)

    # Most positive / negative teams
    sorted_by_sentiment = sorted(rows, key=lambda r: r["avg_sentiment_score"], reverse=True)
    most_positive = [
        {"team": r["team_name"], "sentiment": float(r["avg_sentiment_score"]), "articles": int(r["article_count"])}
        for r in sorted_by_sentiment[:5]
    ]
    most_negative = [
        {"team": r["team_name"], "sentiment": float(r["avg_sentiment_score"]), "articles": int(r["article_count"])}
        for r in sorted_by_sentiment[-5:][::-1]
    ]

    return {
        "matchweek": matchweek_number,
        "summary": {
            "total_goals": total_goals,
            "avg_sentiment": round(float(avg_sentiment), 4),
            "total_articles": total_articles,
        },
        "most_positive_teams": most_positive,
        "most_negative_teams": most_negative,
        "standings": [
            {
                "team": r["team_name"],
                "short_name": r["short_name"],
                "tla": r["tla"],
                "crest_url": r["crest_url"],
                "result": r["result"],
                "goals_for": int(r["goals_for"]),
                "goals_against": int(r["goals_against"]),
                "points": int(r["points"]),
                "avg_sentiment": float(r["avg_sentiment_score"]),
                "article_count": int(r["article_count"]),
                "cumulative_points": int(r["cumulative_points"]),
                "cumulative_gd": int(r["cumulative_gd"]),
            }
            for r in rows
        ],
    }
