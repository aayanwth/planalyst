"""
PLanalyst — FastAPI Router: Predictions endpoints

GET /predictions/title — current title-winner probability per team
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from planalyst.api.database import engine
from planalyst.config import SCHEMA_GOLD

router = APIRouter()


@router.get("/title")
def get_title_predictions():
    """Get current title-winning probability per team."""
    # Check if predictions table exists
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT * FROM {SCHEMA_GOLD}.gold_title_predictions
                ORDER BY win_probability DESC
            """)).mappings().all()
    except ProgrammingError:
        # Table doesn't exist yet — return placeholder
        return {
            "status": "pending",
            "message": "Title predictions not yet computed. Run the model training and prediction pipeline first.",
            "predictions": [],
        }

    if not rows:
        return {
            "status": "pending",
            "message": "No predictions available yet.",
            "predictions": [],
        }

    matchweek = rows[0]["matchweek"] if rows else 0
    model_version = rows[0].get("model_version") or "xgb_v2"
    total_probability = sum(float(r["win_probability"]) for r in rows)

    return {
        "status": "ready",
        "matchweek": matchweek,
        "model_version": model_version,
        "total_probability": round(total_probability, 4),
        "predictions": [
            {
                "team": r["team_name"],
                "win_probability": float(r["win_probability"]),
                "avg_final_points": float(r["avg_final_points"]),
                "avg_final_rank": float(r["avg_final_rank"]),
            }
            for r in rows
        ],
    }
