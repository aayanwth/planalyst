"""
PLanalyst — API response models.

They document the API in /docs, validate what the routers return, and pin the shape the
dashboard depends on. Optional fields are those absent from older Gold tables.
"""

from pydantic import BaseModel


# ── Team ─────────────────────────────────────────────────────────────────────
class SentimentPoint(BaseModel):
    matchweek: int
    avg_sentiment_score: float
    article_count: int


class TeamSentiment(BaseModel):
    team: str
    sentiment_trend: list[SentimentPoint]


class PerformancePoint(BaseModel):
    matchweek: int
    result: str
    goals_for: int
    goals_against: int
    points: int
    goal_difference: int
    cumulative_points: int
    cumulative_gd: int


class TeamPerformance(BaseModel):
    team: str
    performance: list[PerformancePoint]


# ── Matchweek ────────────────────────────────────────────────────────────────
class MatchweekTotals(BaseModel):
    total_goals: int
    avg_sentiment: float
    total_articles: int


class SentimentRank(BaseModel):
    team: str
    sentiment: float
    articles: int


class StandingRow(BaseModel):
    team: str
    short_name: str | None = None
    tla: str | None = None
    crest_url: str | None = None
    result: str
    goals_for: int
    goals_against: int
    points: int
    avg_sentiment: float
    article_count: int
    cumulative_points: int
    cumulative_gd: int


class MatchweekSummary(BaseModel):
    matchweek: int
    summary: MatchweekTotals
    most_positive_teams: list[SentimentRank]
    most_negative_teams: list[SentimentRank]
    standings: list[StandingRow]


# ── Predictions ──────────────────────────────────────────────────────────────
class TitlePrediction(BaseModel):
    team: str
    win_probability: float
    avg_final_points: float
    avg_final_rank: float
    top4_probability: float | None = None
    relegation_probability: float | None = None
    points_p10: float | None = None
    points_p90: float | None = None


class TitlePredictions(BaseModel):
    status: str  # "ready" or "pending"
    message: str | None = None
    matchweek: int | None = None
    model_version: str | None = None
    total_probability: float | None = None
    predictions: list[TitlePrediction]


class HistoryPoint(BaseModel):
    season: int
    matchweek: int
    model_version: str
    team: str
    win_probability: float


class PredictionHistory(BaseModel):
    status: str
    model_version: str | None = None
    history: list[HistoryPoint]


class FixtureForecast(BaseModel):
    match_id: int
    matchweek: int
    kickoff: str | None = None
    home_team: str
    away_team: str
    p_home: float
    p_draw: float
    p_away: float
    played: bool
    score_home: int | None = None
    score_away: int | None = None


class FixtureForecasts(BaseModel):
    status: str
    matchweek: int | None = None
    fixtures: list[FixtureForecast]


class AccuracyMetrics(BaseModel):
    n: int
    log_loss: float
    rps: float
    brier: float
    accuracy: float


class MatchweekAccuracy(AccuracyMetrics):
    matchweek: int


class LiveAccuracy(BaseModel):
    matches_scored: int
    model: AccuracyMetrics | None = None
    baseline: AccuracyMetrics | None = None
    by_matchweek: list[MatchweekAccuracy]


# ── Health ───────────────────────────────────────────────────────────────────
class Health(BaseModel):
    status: str
