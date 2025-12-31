"""Pure parsing/filtering logic in the ingestion layer (no network)."""

import pytest

pytest.importorskip("dlt")

from planalyst.pipelines.news_articles import (  # noqa: E402
    _extract_source_from_url,
    _gdelt_to_article,
    _guardian_to_article,
    _keep_new_in_season,
    _normalize_published_at,
    _published_in_season,
    fetch_rss_articles,
)

SEASON_START = "2026-08-15"


def test_normalize_rfc822_and_iso_to_utc_iso():
    assert _normalize_published_at("Sat, 05 Sep 2026 19:08:30 GMT") == "2026-09-05T19:08:30+00:00"
    assert _normalize_published_at("2026-09-05T20:08:30+01:00") == "2026-09-05T19:08:30+00:00"
    assert _normalize_published_at("2026-09-05T19:08:30Z") == "2026-09-05T19:08:30+00:00"


def test_normalize_rejects_garbage():
    assert _normalize_published_at(None) is None
    assert _normalize_published_at("") is None
    assert _normalize_published_at("not a date") is None


def test_season_bound_rejects_articles_before_kickoff():
    assert not _published_in_season("2026-08-14T23:59:00+00:00", SEASON_START)
    assert _published_in_season("2026-08-15T00:00:00+00:00", SEASON_START)
    assert _published_in_season("Sat, 05 Sep 2026 19:08:30 GMT", SEASON_START)
    assert not _published_in_season("Sat, 01 Mar 2026 12:00:00 GMT", SEASON_START)


def test_season_bound_rejects_missing_or_unparseable_dates():
    assert not _published_in_season(None, SEASON_START)
    assert not _published_in_season("yesterday", SEASON_START)


def test_source_names():
    assert _extract_source_from_url("https://feeds.bbci.co.uk/sport/football/rss.xml") == "BBC Sport"
    assert _extract_source_from_url("https://www.skysports.com/rss/12040") == "Sky Sports"
    assert _extract_source_from_url("https://example.com/feed") == "Unknown"


def _item(title, description="", link="https://bbc.co.uk/a"):
    return {
        "title": title,
        "description": description,
        "link": link,
        "published_at": "2026-09-05T19:08:30+00:00",
        "source_name": "BBC Sport",
    }


def test_rss_filter_matches_team_in_title_or_description_case_insensitively():
    items = [
        _item("Arsenal beat Spurs", link="https://bbc.co.uk/1"),
        _item("Transfer round-up", "Chelsea eye a striker", link="https://bbc.co.uk/2"),
        _item("Weather report", link="https://bbc.co.uk/3"),
    ]
    assert [a["url"] for a in fetch_rss_articles("arsenal", items)] == ["https://bbc.co.uk/1"]
    assert [a["url"] for a in fetch_rss_articles("CHELSEA", items)] == ["https://bbc.co.uk/2"]
    assert fetch_rss_articles("Everton", items) == []


def test_rss_article_has_stable_hash_and_team_query():
    (article,) = fetch_rss_articles("Arsenal", [_item("Arsenal win")])
    (again,) = fetch_rss_articles("Arsenal", [_item("Arsenal win")])
    assert article["url_hash"] == again["url_hash"] and len(article["url_hash"]) == 32
    assert article["team_query"] == "Arsenal" and article["source_name"] == "BBC Sport"


def test_normalize_gdelt_seendate():
    assert _normalize_published_at("20260815T113000Z") == "2026-08-15T11:30:00+00:00"


def test_guardian_result_maps_to_bronze_shape():
    article = _guardian_to_article(
        {
            "webUrl": "https://www.theguardian.com/football/a",
            "webTitle": "Arsenal win again",
            "webPublicationDate": "2026-09-05T19:08:30Z",
            "fields": {"trailText": "Trail", "bodyText": "x" * 6000, "byline": "A Writer"},
        },
        "Arsenal",
    )
    assert article["url"].endswith("/football/a") and article["source_name"] == "The Guardian"
    assert article["published_at"] == "2026-09-05T19:08:30+00:00"
    assert article["description"] == "Trail" and len(article["content"]) == 5000
    assert article["team_query"] == "Arsenal"


def test_guardian_result_without_fields_does_not_crash():
    article = _guardian_to_article({"webUrl": "u", "webTitle": "t"}, "Arsenal")
    assert article["description"] == "" and article["content"] == "" and article["published_at"] is None


def test_gdelt_item_maps_to_bronze_shape():
    article = _gdelt_to_article(
        {"url": "https://punchng.com/x", "title": "Shield", "seendate": "20260815T113000Z",
         "domain": "punchng.com", "socialimage": "https://img"},
        "Arsenal",
    )
    assert article["source_name"] == "punchng.com" and article["content"] == ""
    assert article["published_at"] == "2026-08-15T11:30:00+00:00"


def test_keep_new_in_season_filters_dupes_old_and_urlless():
    def art(url, published):
        return {"url": url, "published_at": published}

    seen = {"https://seen"}
    kept = _keep_new_in_season(
        [
            art("https://ok", "2026-09-01T00:00:00+00:00"),
            art("https://seen", "2026-09-01T00:00:00+00:00"),
            art("https://old", "2026-08-01T00:00:00+00:00"),
            art("", "2026-09-01T00:00:00+00:00"),
            art("https://nodate", None),
            art("https://ok", "2026-09-02T00:00:00+00:00"),
        ],
        seen,
        SEASON_START,
    )
    assert [a["url"] for a in kept] == ["https://ok"]
