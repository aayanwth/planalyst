"""
PLanalyst — FastAPI Router: Predictions endpoints

GET /predictions/title     latest title / top-4 / relegation probabilities
GET /predictions/history   title probability per scored matchweek (latest model version)
GET /predictions/fixtures  forecasts for a matchweek's fixtures (default: the next one to play)
GET /predictions/accuracy  how those forecasts have scored against real results so far
"""

from fastapi import APIRouter, Query
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

from planalyst.api.database import engine
from planalyst.api.schemas import (
    FixtureForecasts,
    LiveAccuracy,
    PredictionHistory,
    TitlePredictions,
)
from planalyst.config import SCHEMA_BRONZE, SCHEMA_GOLD
from planalyst.ml.live_accuracy import compute_live_accuracy

router = APIRouter()

# A table that has not been created yet (pipeline not run) is a normal "pending" state.
MISSING_TABLE = (ProgrammingError, OperationalError)


@router.get("/title", response_model=TitlePredictions)
def get_title_predictions():
    """Get current title-winning probability per team."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT * FROM {SCHEMA_GOLD}.gold_title_predictions
                ORDER BY win_probability DESC
            """)).mappings().all()
    except MISSING_TABLE:
        return {
            "status": "pending",
            "message": "Title predictions not yet computed. Run the model training and prediction pipeline first.",
            "predictions": [],
        }

    if not rows:
        return {"status": "pending", "message": "No predictions available yet.", "predictions": []}

    total_probability = sum(float(r["win_probability"]) for r in rows)

    def optional(row, key):
        value = row.get(key)
        return None if value is None else float(value)

    return {
        "status": "ready",
        "matchweek": rows[0]["matchweek"],
        "model_version": rows[0].get("model_version") or "unknown",
        "total_probability": round(total_probability, 4),
        "predictions": [
            {
                "team": r["team_name"],
                "win_probability": float(r["win_probability"]),
                "avg_final_points": float(r["avg_final_points"]),
                "avg_final_rank": float(r["avg_final_rank"]),
                "top4_probability": optional(r, "top4_probability"),
                "relegation_probability": optional(r, "relegation_probability"),
                "points_p10": optional(r, "points_p10"),
                "points_p90": optional(r, "points_p90"),
            }
            for r in rows
        ],
    }


@router.get("/history", response_model=PredictionHistory)
def get_prediction_history(
    model_version: str | None = Query(
        None, description="Defaults to the model version that scored most recently"
    ),
):
    """Title probability per team for every matchweek the (latest) model has scored."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT season, matchweek, model_version, team_name, win_probability, scored_at
                FROM {SCHEMA_GOLD}.title_prediction_history
                ORDER BY season, matchweek, win_probability DESC
            """)).mappings().all()
    except MISSING_TABLE:
        rows = []

    if not rows:
        return {"status": "pending", "model_version": None, "history": []}

    if model_version is None:
        # Mixing versions would plot two forecasts for the same matchweek on top of each other.
        model_version = max(rows, key=lambda r: str(r["scored_at"]))["model_version"]
    rows = [r for r in rows if r["model_version"] == model_version]

    return {
        "status": "ready" if rows else "pending",
        "model_version": model_version,
        "history": [
            {
                "season": int(r["season"]),
                "matchweek": int(r["matchweek"]),
                "model_version": r["model_version"],
                "team": r["team_name"],
                "win_probability": float(r["win_probability"]),
            }
            for r in rows
        ],
    }


@router.get("/fixtures", response_model=FixtureForecasts)
def get_fixture_forecasts(
    matchweek: int | None = Query(
        None, description="Matchweek to show; defaults to the next one with unplayed fixtures"
    ),
):
    """Forecast [home / draw / away] for each fixture of a matchweek."""
    try:
        with engine.connect() as conn:
            if matchweek is None:
                matchweek = conn.execute(text(f"""
                    SELECT MIN(fp.matchday)
                    FROM {SCHEMA_GOLD}.fixture_predictions fp
                    JOIN {SCHEMA_BRONZE}.raw_matches m ON m.id = fp.match_id
                    WHERE m.status != 'FINISHED'
                """)).scalar()
            if matchweek is None:
                return {"status": "pending", "matchweek": None, "fixtures": []}
            rows = conn.execute(
                text(f"""
                    SELECT fp.match_id, fp.matchday, fp.utc_date, fp.home_team_name,
                           fp.away_team_name, fp.p_home, fp.p_draw, fp.p_away,
                           m.status, m.score_home, m.score_away
                    FROM {SCHEMA_GOLD}.fixture_predictions fp
                    JOIN {SCHEMA_BRONZE}.raw_matches m ON m.id = fp.match_id
                    WHERE fp.matchday = :mw
                    ORDER BY fp.utc_date, fp.match_id
                """),
                {"mw": int(matchweek)},
            ).mappings().all()
    except MISSING_TABLE:
        return {"status": "pending", "matchweek": None, "fixtures": []}

    return {
        "status": "ready" if rows else "pending",
        "matchweek": int(matchweek),
        "fixtures": [
            {
                "match_id": int(r["match_id"]),
                "matchweek": int(r["matchday"]),
                "kickoff": None if r["utc_date"] is None else str(r["utc_date"]),
                "home_team": r["home_team_name"],
                "away_team": r["away_team_name"],
                "p_home": float(r["p_home"]),
                "p_draw": float(r["p_draw"]),
                "p_away": float(r["p_away"]),
                "played": r["status"] == "FINISHED",
                "score_home": None if r["score_home"] is None else int(r["score_home"]),
                "score_away": None if r["score_away"] is None else int(r["score_away"]),
            }
            for r in rows
        ],
    }


@router.get("/accuracy", response_model=LiveAccuracy)
def get_live_accuracy():
    """Out-of-sample record: forecasts stored before kick-off vs the results that followed."""
    try:
        return compute_live_accuracy(engine)
    except MISSING_TABLE:
        return {"matches_scored": 0, "model": None, "baseline": None, "by_matchweek": []}
