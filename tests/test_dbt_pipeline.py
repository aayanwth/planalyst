"""
dbt integration test: build the Silver/Gold models on a hand-made league in a real Postgres and
check the numbers against values worked out by hand (tests/dbt_fixture.sql).

Needs a reachable Postgres server; skipped otherwise. Locally:
    PLANALYST_TEST_PG=localhost:5433 pytest tests/test_dbt_pipeline.py
CI points the same variable at a service container. A scratch database is created and dropped,
so no existing data is touched.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pg = os.getenv("PLANALYST_TEST_PG")
pytestmark = [
    pytest.mark.skipif(not pg, reason="set PLANALYST_TEST_PG=host:port to run against Postgres"),
    pytest.mark.skipif(shutil.which("dbt") is None, reason="dbt is not installed"),
]

ROOT = Path(__file__).resolve().parent.parent
DB = "planalyst_dbt_test"
USER = os.getenv("PLANALYST_TEST_USER", "planalyst")
PASSWORD = os.getenv("PLANALYST_TEST_PASSWORD", "planalyst_dev")


def _engine(database: str):
    from sqlalchemy import create_engine

    host, port = pg.split(":")
    return create_engine(
        f"postgresql+psycopg2://{USER}:{PASSWORD}@{host}:{port}/{database}",
        isolation_level="AUTOCOMMIT",
    )


def _dbt(*args: str):
    host, port = pg.split(":")
    env = {
        **os.environ,
        "POSTGRES_HOST": host,
        "POSTGRES_PORT": port,
        "POSTGRES_USER": USER,
        "POSTGRES_PASSWORD": PASSWORD,
        "POSTGRES_DB": DB,
    }
    project = str(ROOT / "dbt_project")
    return subprocess.run(
        ["dbt", *args, "--project-dir", project, "--profiles-dir", project],
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def built():
    from sqlalchemy import text

    admin = _engine("postgres")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {DB}"))
        conn.execute(text(f"CREATE DATABASE {DB}"))
    engine = _engine(DB)
    fixture_sql = (ROOT / "tests" / "dbt_fixture.sql").read_text(encoding="utf-8")
    with engine.connect() as conn:
        conn.exec_driver_sql(fixture_sql)

    for step in (["seed"], ["run"], ["test"]):
        result = _dbt(*step)
        assert result.returncode == 0, f"dbt {' '.join(step)} failed:\n{result.stdout[-3000:]}"
    yield engine
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {DB}"))


def _fact(engine):
    import pandas as pd

    return pd.read_sql(
        "SELECT team_name, matchweek_number AS mw, result, points, avg_sentiment_score AS sent, "
        "article_count AS n, cumulative_points AS cum FROM public_gold.fact_team_sentiment_performance",
        engine,
    ).set_index(["team_name", "mw"])


def test_results_and_points_are_correct(built):
    fact = _fact(built)
    assert fact.loc[("Arsenal", 1), "result"] == "W" and fact.loc[("Arsenal", 1), "points"] == 3
    assert fact.loc[("Liverpool", 1), "result"] == "D"
    assert fact.loc[("Liverpool", 2), "cum"] == 4  # D then W
    assert fact.loc[("Arsenal", 2), "cum"] == 6


def test_only_played_matchweeks_are_in_the_fact_table(built):
    assert set(_fact(built).index.get_level_values("mw")) == {1, 2}


def test_head_to_head_preview_credits_subject_and_inverts_for_opponent(built):
    fact = _fact(built)
    assert fact.loc[("Arsenal", 1), "sent"] == pytest.approx(0.9)
    assert fact.loc[("Chelsea", 1), "sent"] == pytest.approx(-0.9)
    assert fact.loc[("Arsenal", 1), "n"] == 1 and fact.loc[("Chelsea", 1), "n"] == 1


def test_single_club_article_goes_to_the_next_match(built):
    fact = _fact(built)
    assert fact.loc[("Liverpool", 2), "sent"] == pytest.approx(-0.8)
    assert fact.loc[("Liverpool", 2), "n"] == 1


def test_article_naming_no_club_falls_back_to_the_club_it_was_searched_for(built):
    fact = _fact(built)
    assert fact.loc[("Everton", 1), "n"] == 1
    assert fact.loc[("Everton", 1), "sent"] == pytest.approx(0.0)  # NEUTRAL scores as 0


def test_two_clubs_without_a_shared_fixture_credit_only_the_first_named(built):
    fact = _fact(built)
    assert fact.loc[("Chelsea", 2), "sent"] == pytest.approx(0.5)
    assert fact.loc[("Everton", 2), "n"] == 0


def test_round_ups_count_for_nobody(built):
    # "Saturday gossip: Arsenal, Chelsea and Liverpool ..." must not appear anywhere
    assert _fact(built)["n"].sum() == 5  # u1 x2 clubs, u2, u5, u6


def test_match_report_is_attributed_to_the_following_match_never_the_one_it_reports(built):
    import pandas as pd

    rows = pd.read_sql(
        "SELECT team_name, next_matchweek, polarity FROM public_silver.silver_article_teams "
        "WHERE article_url = 'u4' ORDER BY team_name",
        built,
    )
    assert list(rows["next_matchweek"]) == [3, 3]  # not MW2, which kicked off before publication
    assert dict(zip(rows["team_name"], rows["polarity"])) == {"Arsenal": 1, "Everton": -1}
