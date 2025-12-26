"""
PLanalyst — dlt Pipeline: News Articles Ingestion (Bronze Layer)

Ingests Premier League news articles from the Guardian Open Platform (full text,
searchable by date range) and GDELT DOC 2.0 (many outlets, no key, ~3 months of history)
into the bronze.raw_news_articles table in PostgreSQL.

Scope: 2026-2027 season ONLY (date-bounded queries).
Falls back to RSS scraping (BBC Sport, Sky Sports) for a team when neither API returns anything.
"""

import hashlib
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Generator
from xml.etree import ElementTree

import dlt
import requests

from planalyst.config import (
    GUARDIAN_API_KEY,
    PL_SEASON_START_DATE,
    POSTGRES_CONNECTION_STRING,
    SCHEMA_BRONZE,
)

# ── Team name search queries ─────────────────────────────────────────────────
# Map canonical team names to effective search queries for news APIs.
# Some teams need shorter/more common names to get good results.
TEAM_SEARCH_QUERIES = {
    "Arsenal FC": "Arsenal",
    "Aston Villa FC": "Aston Villa",
    "AFC Bournemouth": "Bournemouth",
    "Brentford FC": "Brentford",
    "Brighton & Hove Albion FC": "Brighton",
    "Chelsea FC": "Chelsea",
    "Coventry City FC": "Coventry City",
    "Crystal Palace FC": "Crystal Palace",
    "Everton FC": "Everton",
    "Fulham FC": "Fulham",
    "Hull City AFC": "Hull City",
    "Ipswich Town FC": "Ipswich Town",
    "Leeds United FC": "Leeds United",
    "Liverpool FC": "Liverpool",
    "Manchester City FC": "Manchester City",
    "Manchester United FC": "Manchester United",
    "Newcastle United FC": "Newcastle United",
    "Nottingham Forest FC": "Nottingham Forest",
    "Sunderland AFC": "Sunderland",
    "Tottenham Hotspur FC": "Tottenham",
}

# Reverse lookup for when we only have short names
TEAM_SHORT_TO_FULL = {v: k for k, v in TEAM_SEARCH_QUERIES.items()}


# ── RSS Feed URLs ─────────────────────────────────────────────────────────────
RSS_FEEDS = [
    "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "https://www.skysports.com/rss/12040",  # Sky Sports Football
]


# ── Guardian Open Platform Client ────────────────────────────────────────────

class GuardianClient:
    """Client for the Guardian Open Platform (free key, archive back to 1999)."""

    BASE_URL = "https://content.guardianapis.com/search"
    MAX_PAGES = 4  # 4 x 50 = up to 200 articles per team

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()

    def search_articles(self, query: str, from_date: str, to_date: str) -> list[dict]:
        """Return normalised football articles mentioning `query` in the date range."""
        articles: list[dict] = []
        for page in range(1, self.MAX_PAGES + 1):
            params = {
                "q": f'"{query}"',
                "section": "football",
                "from-date": from_date,
                "to-date": to_date,
                "order-by": "newest",
                "page-size": 50,
                "page": page,
                "show-fields": "trailText,bodyText,byline,thumbnail",
                "api-key": self.api_key,
            }
            response = self.session.get(self.BASE_URL, params=params, timeout=30)
            if response.status_code in (401, 403):
                raise ValueError(
                    f"Guardian API returned {response.status_code}. "
                    "Check GUARDIAN_API_KEY in .env (free key: https://open-platform.theguardian.com/access/)."
                )
            if response.status_code == 429:
                print("  ⏳ Guardian API rate limited. Waiting 5s...")
                time.sleep(5)
                response = self.session.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()

            body = response.json().get("response", {})
            articles.extend(_guardian_to_article(r, query) for r in body.get("results", []))
            if page >= body.get("pages", 1):
                break
            time.sleep(0.2)  # free tier allows 12 calls/second; stay well below
        return articles


def _guardian_to_article(result: dict, team_query: str) -> dict:
    """Map one Guardian search result onto the bronze article shape."""
    fields = result.get("fields") or {}
    return {
        "url": result.get("webUrl", ""),
        "title": result.get("webTitle", ""),
        "description": fields.get("trailText", ""),
        "content": (fields.get("bodyText") or "")[:5000],
        "source_name": "The Guardian",
        "source_id": "the-guardian",
        "author": fields.get("byline"),
        "published_at": _normalize_published_at(result.get("webPublicationDate")),
        "url_to_image": fields.get("thumbnail"),
        "team_query": team_query,
    }


# ── GDELT DOC 2.0 Client ─────────────────────────────────────────────────────

class GdeltClient:
    """Client for the GDELT DOC 2.0 article search (no key; ~3 months of history)."""

    BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
    MIN_INTERVAL_S = 8.0  # GDELT asks for one request per 5s but still throttles at that pace
    MAX_ATTEMPTS = 4  # on HTTP 429 the wait grows: 8s, 16s, 24s, 32s

    def __init__(self):
        self.session = requests.Session()
        self._last_call = 0.0

    def search_articles(self, query: str, from_date: str, to_date: str) -> list[dict]:
        """Return normalised English articles about `query` + Premier League in the range."""
        params = {
            "query": f'"{query}" "Premier League" sourcelang:english',
            "mode": "artlist",
            "format": "json",
            "maxrecords": 250,
            "sort": "datedesc",
            "startdatetime": from_date.replace("-", "") + "000000",
            "enddatetime": to_date.replace("-", "") + "235959",
        }
        for attempt in range(self.MAX_ATTEMPTS):
            wait = self.MIN_INTERVAL_S * (attempt + 1) - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            response = self.session.get(self.BASE_URL, params=params, timeout=60)
            self._last_call = time.monotonic()
            if response.status_code != 429:
                break
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            # GDELT answers with a plain-text message when throttled or the query is rejected
            raise RuntimeError(f"GDELT returned non-JSON: {response.text[:120]!r}")
        return [_gdelt_to_article(a, query) for a in payload.get("articles", [])]


def _gdelt_to_article(item: dict, team_query: str) -> dict:
    """Map one GDELT artlist entry onto the bronze article shape (titles only, no body)."""
    return {
        "url": item.get("url", ""),
        "title": item.get("title", ""),
        "description": "",
        "content": "",
        "source_name": item.get("domain", ""),
        "source_id": None,
        "author": None,
        "published_at": _normalize_published_at(item.get("seendate")),
        "url_to_image": item.get("socialimage"),
        "team_query": team_query,
    }


# ── RSS Scraper ──────────────────────────────────────────────────────────────

def fetch_rss_items() -> list[dict]:
    """Download every RSS feed once and return normalised in-season items."""
    items = []
    for feed_url in RSS_FEEDS:
        try:
            response = requests.get(feed_url, timeout=10)
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
        except Exception as e:
            print(f"  ⚠️ RSS feed error ({feed_url}): {e}")
            continue

        for item in root.findall(".//item"):
            link = item.findtext("link", "")
            published_at = _normalize_published_at(item.findtext("pubDate", ""))
            if not link or not _published_in_season(published_at, PL_SEASON_START_DATE):
                continue
            items.append({
                "link": link,
                "title": item.findtext("title", ""),
                "description": item.findtext("description", ""),
                "published_at": published_at,
                "source_name": _extract_source_from_url(feed_url),
            })
    return items


def fetch_rss_articles(team_query: str, items: list[dict] | None = None) -> list[dict]:
    """
    Filter RSS items that mention a specific team.
    Falls back to this when the news APIs return nothing. Pass `items` to avoid
    re-downloading the feeds for every team.
    """
    if items is None:
        items = fetch_rss_items()
    team_lower = team_query.lower()
    articles = []

    for item in items:
        if team_lower not in f"{item['title']} {item['description']}".lower():
            continue
        articles.append({
            "url": item["link"],
            "url_hash": hashlib.md5(item["link"].encode()).hexdigest(),
            "title": item["title"],
            "description": item["description"],
            "content": item["description"],  # RSS usually only has description
            "source_name": item["source_name"],
            "source_id": None,
            "author": None,
            "published_at": item["published_at"],
            "url_to_image": None,
            "team_query": team_query,
        })
    return articles


def _normalize_published_at(value: str | None) -> str | None:
    """Convert RFC-822 / ISO timestamps to ISO-8601 UTC so the column has one type."""
    if not value:
        return None
    text_value = str(value).strip()
    try:
        if len(text_value) == 16 and text_value[8] == "T" and text_value.endswith("Z"):
            parsed = datetime.strptime(text_value, "%Y%m%dT%H%M%SZ")  # GDELT seendate
        elif len(text_value) >= 10 and text_value[4] == "-":
            parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
        else:
            parsed = parsedate_to_datetime(text_value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def _extract_source_from_url(url: str) -> str:
    """Extract a human-readable source name from a feed URL."""
    if "bbc" in url:
        return "BBC Sport"
    elif "skysports" in url:
        return "Sky Sports"
    return "Unknown"


def _published_in_season(published_at: str | None, season_start: str) -> bool:
    """Reject articles dated before the live season start."""
    if not published_at:
        return False
    text_value = str(published_at).strip()
    try:
        if len(text_value) >= 10 and text_value[4] == "-":
            article_date = datetime.fromisoformat(text_value.replace("Z", "+00:00")).date()
        else:
            article_date = parsedate_to_datetime(text_value).date()
        return article_date.isoformat() >= season_start
    except Exception:
        return False


def _keep_new_in_season(
    articles: list[dict], seen_urls: set[str], season_start: str
) -> list[dict]:
    """Drop articles without a URL, already seen this run, or dated outside the season."""
    kept = []
    for article in articles:
        url = article["url"]
        if not url or url in seen_urls:
            continue
        if not _published_in_season(article["published_at"], season_start):
            continue
        seen_urls.add(url)
        kept.append(article)
    return kept


# ── dlt Resource ─────────────────────────────────────────────────────────────

@dlt.resource(
    name="raw_news_articles",
    write_disposition="merge",
    primary_key="url",
)
def raw_news_articles_resource(
    guardian_key: str = GUARDIAN_API_KEY,
    season_start: str = PL_SEASON_START_DATE,
    use_gdelt: bool = True,
    use_rss_fallback: bool = True,
) -> Generator[dict[str, Any], None, None]:
    """
    dlt resource that yields news articles about PL teams.

    Queries the Guardian (if a key is set) and GDELT for every team, then falls back to
    RSS for any team that got nothing. Date-bounded to the current season only.
    """
    use_guardian = bool(guardian_key and guardian_key != "your_guardian_api_key_here")
    guardian_client = GuardianClient(guardian_key) if use_guardian else None
    gdelt_client = GdeltClient() if use_gdelt else None
    if not use_guardian:
        print("  ⚠️ GUARDIAN_API_KEY not set; skipping the Guardian source")

    # Date bounds for the current season
    from_date = season_start
    to_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    seen_urls = set()
    total_articles = 0
    rss_items = None  # downloaded lazily, once per run

    # Get list of teams to search
    teams_to_search = list(TEAM_SEARCH_QUERIES.values())

    for team_query in teams_to_search:
        print(f"  📰 Fetching news for: {team_query}")
        articles = []

        # --- Guardian, then GDELT ---
        if guardian_client:
            try:
                articles += _keep_new_in_season(
                    guardian_client.search_articles(team_query, from_date, to_date),
                    seen_urls, from_date,
                )
            except ValueError as e:  # bad key: don't retry for the other teams
                print(f"     ⚠️ Guardian auth error: {e}")
                guardian_client = None
            except Exception as e:
                print(f"     ⚠️ Guardian error: {e}")
            print(f"     Guardian: {len(articles)} articles")

        if gdelt_client:
            before = len(articles)
            try:
                articles += _keep_new_in_season(
                    gdelt_client.search_articles(team_query, from_date, to_date),
                    seen_urls, from_date,
                )
            except Exception as e:
                print(f"     ⚠️ GDELT error: {e}")
            print(f"     GDELT: {len(articles) - before} articles")

        # --- RSS fallback ---
        if (not articles) and use_rss_fallback:
            if rss_items is None:
                rss_items = fetch_rss_items()
            rss_articles = fetch_rss_articles(team_query, rss_items)
            for a in rss_articles:
                if a["url"] not in seen_urls:
                    seen_urls.add(a["url"])
                    articles.append(a)
            if rss_articles:
                print(f"     RSS fallback: {len(rss_articles)} articles")

        # Yield all articles for this team
        for article in articles:
            article["ingested_at"] = datetime.now(timezone.utc).isoformat()
            total_articles += 1
            yield article

    print(f"\n  📊 Total articles ingested: {total_articles}")


# ── dlt Pipeline ─────────────────────────────────────────────────────────────

def create_pipeline() -> dlt.Pipeline:
    """Create the news articles dlt pipeline targeting bronze schema."""
    return dlt.pipeline(
        pipeline_name="planalyst_news_articles",
        destination=dlt.destinations.postgres(credentials=POSTGRES_CONNECTION_STRING),
        dataset_name=SCHEMA_BRONZE,
    )


def run_pipeline() -> None:
    """Run the news articles ingestion pipeline."""
    pipeline = create_pipeline()
    resource = raw_news_articles_resource()

    print(f"\n🚀 Running news articles pipeline → {SCHEMA_BRONZE}.raw_news_articles")
    load_info = pipeline.run(resource)
    print("✅ Load complete!")
    print(f"   {load_info}")


# ── CLI Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_pipeline()
