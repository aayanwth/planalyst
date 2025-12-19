"""
PLanalyst — FastAPI Router: Team endpoints

GET /team/{team_name}/sentiment — sentiment trend over matchweeks
GET /team/{team_name}/performance — results + points over matchweeks
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from planalyst.api.database import engine

router = APIRouter()


@router.get("/{team_name}/sentiment")
def get_team_sentiment(team_name: str):
    """Get sentiment trend for a team across matchweeks."""
    query = text("""
        SELECT
            team_name, matchweek_number,
            avg_sentiment_score, article_count
        FROM public_gold.fact_team_sentiment_performance
        WHERE LOWER(team_name) = LOWER(:team_name)
        ORDER BY matchweek_number
    """)
    with engine.connect() as conn:
        rows = conn.execute(query, {"team_name": team_name}).mappings().all()

    if not rows:
        raise HTTPException(status_code=404, detail=f"Team '{team_name}' not found")

    return {
        "team": team_name,
        "sentiment_trend": [
            {
                "matchweek": r["matchweek_number"],
                "avg_sentiment_score": float(r["avg_sentiment_score"]),
                "article_count": int(r["article_count"]),
            }
            for r in rows
        ],
    }


@router.get("/{team_name}/performance")
def get_team_performance(team_name: str):
    """Get performance (results, goals, points) for a team across matchweeks."""
    query = text("""
        SELECT
            team_name, matchweek_number,
            result, goals_for, goals_against, points, goal_difference,
            cumulative_points, cumulative_gd
        FROM public_gold.fact_team_sentiment_performance
        WHERE LOWER(team_name) = LOWER(:team_name)
        ORDER BY matchweek_number
    """)
    with engine.connect() as conn:
        rows = conn.execute(query, {"team_name": team_name}).mappings().all()

    if not rows:
        raise HTTPException(status_code=404, detail=f"Team '{team_name}' not found")

    return {
        "team": team_name,
        "performance": [
            {
                "matchweek": r["matchweek_number"],
                "result": r["result"],
                "goals_for": int(r["goals_for"]),
                "goals_against": int(r["goals_against"]),
                "points": int(r["points"]),
                "goal_difference": int(r["goal_difference"]),
                "cumulative_points": int(r["cumulative_points"]),
                "cumulative_gd": int(r["cumulative_gd"]),
            }
            for r in rows
        ],
    }
