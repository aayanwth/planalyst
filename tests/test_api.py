"""API tests against an in-memory SQLite database that mimics the Postgres schemas."""

import math

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from planalyst.api import main as api_main
from planalyst.api.main import app
from planalyst.api.routers import matchweek, predictions, team

FACT_COLUMNS = (
    "team_name TEXT, matchweek_number INT, result TEXT, goals_for INT, goals_against INT, "
    "points INT, goal_difference INT, cumulative_points INT, cumulative_gd INT, "
    "avg_sentiment_score REAL, article_count INT"
)


@pytest.fixture()
def client(monkeypatch, sqlite_engine):
    engine = sqlite_engine
    with engine.begin() as conn:
        conn.execute(
            text(f"CREATE TABLE public_gold.fact_team_sentiment_performance ({FACT_COLUMNS})")
        )
        conn.execute(
            text(
                "CREATE TABLE public_gold.dim_team "
                "(team_name TEXT, short_name TEXT, crest_url TEXT, tla TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE gold.gold_title_predictions (team_name TEXT, win_probability REAL, "
                "avg_final_points REAL, avg_final_rank REAL, matchweek INT, model_version TEXT)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO public_gold.fact_team_sentiment_performance VALUES "
                "('Arsenal',1,'W',2,0,3,2,3,2,0.40,4),"
                "('Arsenal',2,'D',1,1,1,0,4,2,0.10,2),"
                "('Chelsea',1,'L',0,1,0,-1,0,-1,-0.30,3),"
                "('Chelsea',2,'W',3,0,3,3,3,2,0.20,1)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO public_gold.dim_team VALUES "
                "('Arsenal','Arsenal','a.png','ARS'),('Chelsea','Chelsea','c.png','CHE')"
            )
        )
    for module in (team, matchweek, predictions, api_main):
        monkeypatch.setattr(module, "engine", engine)
    client = TestClient(app)
    client.engine = engine
    return client


# ── Health and CORS ──────────────────────────────────────────────────────────
def test_health_is_liveness_only(client):
    assert client.get("/health").json() == {"status": "healthy"}


def test_ready_checks_the_database(client, monkeypatch, tmp_path):
    assert client.get("/ready").json() == {"status": "ready"}
    broken = create_engine(f"sqlite:///{tmp_path / 'missing_dir' / 'x.db'}")
    monkeypatch.setattr(api_main, "engine", broken)
    response = client.get("/ready")
    assert response.status_code == 503 and "database unavailable" in response.json()["detail"]


def test_cors_allows_only_the_dashboard_origin(client):
    ok = client.get("/health", headers={"Origin": "http://localhost:8501"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:8501"
    other = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_openapi_documents_the_response_models(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert {"TitlePredictions", "LiveAccuracy", "FixtureForecasts", "MatchweekSummary"} <= set(schemas)


# ── Team and matchweek ───────────────────────────────────────────────────────
def test_team_sentiment_is_case_insensitive_and_ordered(client):
    body = client.get("/team/arsenal/sentiment").json()
    assert [p["matchweek"] for p in body["sentiment_trend"]] == [1, 2]
    assert body["sentiment_trend"][0] == {
        "matchweek": 1,
        "avg_sentiment_score": pytest.approx(0.40),
        "article_count": 4,
    }


def test_team_performance(client):
    body = client.get("/team/Chelsea/performance").json()
    assert [p["points"] for p in body["performance"]] == [0, 3]
    assert body["performance"][1]["cumulative_points"] == 3


def test_unknown_team_is_404(client):
    assert client.get("/team/Nowhere FC/sentiment").status_code == 404
    assert client.get("/team/Nowhere FC/performance").status_code == 404


def test_matchweek_summary_orders_standings_and_aggregates(client):
    body = client.get("/matchweek/2/summary").json()
    assert [r["team"] for r in body["standings"]] == ["Arsenal", "Chelsea"]  # 4 pts vs 3
    assert body["summary"]["total_goals"] == 4
    assert body["summary"]["total_articles"] == 3
    assert body["summary"]["avg_sentiment"] == pytest.approx(0.15)
    assert body["most_positive_teams"][0]["team"] == "Chelsea"


def test_unknown_matchweek_is_404(client):
    assert client.get("/matchweek/99/summary").status_code == 404


# ── Title predictions ────────────────────────────────────────────────────────
def test_predictions_empty_table_reports_pending(client):
    body = client.get("/predictions/title").json()
    assert body["status"] == "pending" and body["predictions"] == []


def test_predictions_ready_from_an_older_table_without_the_new_columns(client):
    with client.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO gold.gold_title_predictions VALUES "
                "('Arsenal',0.7,88.1,1.3,5,'xgb_v2'),('Chelsea',0.3,80.2,2.1,5,'xgb_v2')"
            )
        )
    body = client.get("/predictions/title").json()
    assert body["status"] == "ready" and body["matchweek"] == 5
    assert body["total_probability"] == pytest.approx(1.0)
    assert [p["team"] for p in body["predictions"]] == ["Arsenal", "Chelsea"]
    assert body["predictions"][0]["top4_probability"] is None  # column absent -> null, not an error


def test_predictions_include_top4_relegation_and_points_range_when_available(client):
    with client.engine.begin() as conn:
        conn.execute(text("DROP TABLE gold.gold_title_predictions"))
        conn.execute(
            text(
                "CREATE TABLE gold.gold_title_predictions (team_name TEXT, win_probability REAL, "
                "avg_final_points REAL, avg_final_rank REAL, matchweek INT, model_version TEXT, "
                "top4_probability REAL, relegation_probability REAL, points_p10 REAL, points_p90 REAL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO gold.gold_title_predictions VALUES "
                "('Arsenal',1.0,88.1,1.0,5,'blend_v3',0.99,0.0,80,95)"
            )
        )
    p = client.get("/predictions/title").json()["predictions"][0]
    assert (p["top4_probability"], p["relegation_probability"]) == (0.99, 0.0)
    assert (p["points_p10"], p["points_p90"]) == (80, 95)


# ── History ──────────────────────────────────────────────────────────────────
HISTORY_DDL = (
    "CREATE TABLE gold.title_prediction_history (season INT, matchweek INT, model_version TEXT, "
    "team_name TEXT, win_probability REAL, scored_at TEXT)"
)


def test_history_pending_when_table_missing(client):
    body = client.get("/predictions/history").json()
    assert body["status"] == "pending" and body["history"] == []


def test_history_ready_ordered_and_limited_to_the_latest_model_version(client):
    with client.engine.begin() as conn:
        conn.execute(text(HISTORY_DDL))
        conn.execute(
            text(
                "INSERT INTO gold.title_prediction_history VALUES "
                "(2026,5,'xgb_v2','Arsenal',0.9,'2026-10-01 10:00:00'),"
                "(2026,5,'blend_v3','Arsenal',0.4,'2026-10-05 10:00:00'),"
                "(2026,5,'blend_v3','Chelsea',0.1,'2026-10-05 10:00:00'),"
                "(2026,6,'blend_v3','Arsenal',0.5,'2026-10-12 10:00:00')"
            )
        )
    body = client.get("/predictions/history").json()
    assert body["model_version"] == "blend_v3"  # not two forecasts stacked on matchweek 5
    assert [(h["matchweek"], h["team"]) for h in body["history"]] == [
        (5, "Arsenal"),
        (5, "Chelsea"),
        (6, "Arsenal"),
    ]
    old = client.get("/predictions/history", params={"model_version": "xgb_v2"}).json()
    assert [h["win_probability"] for h in old["history"]] == [0.9]


# ── Fixture forecasts and live accuracy ──────────────────────────────────────
@pytest.fixture()
def forecasts(client):
    with client.engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE bronze.raw_matches (id INT, status TEXT, score_home INT, score_away INT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE gold.fixture_predictions (match_id INT, season INT, matchday INT, "
                "utc_date TEXT, home_team_name TEXT, away_team_name TEXT, p_home REAL, p_draw REAL, "
                "p_away REAL, model_version TEXT)"
            )
        )
        conn.execute(
            text("CREATE TABLE training.historical_matches (score_home INT, score_away INT)")
        )
        conn.execute(
            text(
                "INSERT INTO bronze.raw_matches VALUES "
                "(1,'FINISHED',2,1),(2,'FINISHED',1,1),(3,'TIMED',NULL,NULL),(4,'TIMED',NULL,NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO gold.fixture_predictions VALUES "
                "(1,2026,5,'2026-10-03T15:00:00+00:00','Arsenal','Chelsea',0.5,0.3,0.2,'blend_v3'),"
                "(2,2026,5,'2026-10-03T17:30:00+00:00','Everton','Fulham',0.2,0.3,0.5,'blend_v3'),"
                "(3,2026,6,'2026-10-10T15:00:00+00:00','Arsenal','Everton',0.6,0.25,0.15,'blend_v3'),"
                "(4,2026,6,'2026-10-10T12:30:00+00:00','Chelsea','Fulham',0.4,0.3,0.3,'blend_v3')"
            )
        )
        # 4 home wins, 4 draws, 2 away wins -> baseline [0.4, 0.4, 0.2]
        conn.execute(
            text(
                "INSERT INTO training.historical_matches VALUES "
                "(1,0),(2,0),(3,1),(1,0),(1,1),(0,0),(2,2),(1,1),(0,1),(0,2)"
            )
        )
    return client


def test_fixtures_default_to_the_next_matchweek_in_kickoff_order(forecasts):
    body = forecasts.get("/predictions/fixtures").json()
    assert body["status"] == "ready" and body["matchweek"] == 6
    assert [f["home_team"] for f in body["fixtures"]] == ["Chelsea", "Arsenal"]  # 12:30 before 15:00
    assert not any(f["played"] for f in body["fixtures"])
    assert body["fixtures"][1]["p_home"] == pytest.approx(0.6)


def test_fixtures_for_a_played_matchweek_show_the_result(forecasts):
    body = forecasts.get("/predictions/fixtures", params={"matchweek": 5}).json()
    assert [f["played"] for f in body["fixtures"]] == [True, True]
    assert (body["fixtures"][0]["score_home"], body["fixtures"][0]["score_away"]) == (2, 1)


def test_fixtures_pending_when_nothing_stored(client):
    assert client.get("/predictions/fixtures").json()["status"] == "pending"


def test_live_accuracy_matches_a_hand_calculation(forecasts):
    body = forecasts.get("/predictions/accuracy").json()
    assert body["matches_scored"] == 2  # only the two finished matches
    # match 1: home win forecast 0.5 -> -ln .5; match 2: draw forecast 0.3 -> -ln .3
    assert body["model"]["log_loss"] == pytest.approx((-math.log(0.5) - math.log(0.3)) / 2)
    assert body["model"]["accuracy"] == pytest.approx(0.5)  # home call right, away call wrong
    # baseline [0.4, 0.4, 0.2]: -ln .4 for the home win and for the draw
    assert body["baseline"]["log_loss"] == pytest.approx(-math.log(0.4))
    assert [w["matchweek"] for w in body["by_matchweek"]] == [5]


def test_live_accuracy_with_no_results_yet_or_no_tables(client):
    body = client.get("/predictions/accuracy").json()  # tables do not exist yet
    assert body == {"matches_scored": 0, "model": None, "baseline": None, "by_matchweek": []}
