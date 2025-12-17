"""
PLanalyst — dlt Pipeline: News Articles Ingestion (Bronze Layer)

Ingests Premier League news articles from NewsAPI (and/or RSS feeds)
into the bronze.raw_news_articles table in PostgreSQL.

Scope: 2026-2027 season ONLY (date-bounded queries).
Falls back to RSS scraping (BBC Sport, Sky Sports) if NewsAPI is unavailable.
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
    NEWS_API_KEY,
    PL_SEASON_START_DATE,
    PL_TEAMS_SHORT,
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


# ── NewsAPI Client ───────────────────────────────────────────────────────────

class NewsAPIClient:
    """Client for NewsAPI.org with rate limiting."""

    BASE_URL = "https://newsapi.org/v2"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()

    def search_articles(
        self,
        query: str,
        from_date: str | None = None,
        to_date: str | None = None,
        page_size: int = 100,
        page: int = 1,
    ) -> dict:
        """Search for articles matching a query."""
        params = {
            "q": f'"{query}" AND "Premier League"',
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": page_size,
            "page": page,
            "apiKey": self.api_key,
        }
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        response = self.session.get(f"{self.BASE_URL}/everything", params=params)

        if response.status_code == 429:
            print("  ⏳ NewsAPI rate limited. Waiting 60s...")
            time.sleep(60)
            response = self.session.get(f"{self.BASE_URL}/everything", params=params)

        if response.status_code == 401:
            raise ValueError(
                f"NewsAPI returned 401 (Unauthorized). "
                f"Check your NEWS_API_KEY in .env. "
                f"Get a free key at https://newsapi.org/"
            )

        response.raise_for_status()
        return response.json()


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
    Falls back to this when NewsAPI is unavailable. Pass `items` to avoid
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
        if len(text_value) >= 10 and text_value[4] == "-":
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


# ── dlt Resource ─────────────────────────────────────────────────────────────

@dlt.resource(
    name="raw_news_articles",
    write_disposition="merge",
    primary_key="url",
)
def raw_news_articles_resource(
    api_key: str = NEWS_API_KEY,
    season_start: str = PL_SEASON_START_DATE,
    use_rss_fallback: bool = True,
) -> Generator[dict[str, Any], None, None]:
    """
    dlt resource that yields news articles about PL teams.

    Tries NewsAPI first; if unavailable (no key / 401), falls back to RSS.
    Date-bounded to the current season only.
    """
    use_newsapi = bool(api_key and api_key != "your_newsapi_org_api_key_here")
    newsapi_client = NewsAPIClient(api_key) if use_newsapi else None

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

        # --- Try NewsAPI first ---
        if use_newsapi and newsapi_client:
            try:
                data = newsapi_client.search_articles(
                    query=team_query,
                    from_date=from_date,
                    to_date=to_date,
                    page_size=50,
                )
                if data.get("status") == "ok":
                    for a in data.get("articles", []):
                        url = a.get("url", "")
                        if not url or url in seen_urls:
                            continue
                        if a.get("title") == "[Removed]":
                            continue

                        # Validate date is within season
                        pub_date = _normalize_published_at(a.get("publishedAt")) or ""
                        if pub_date and pub_date[:10] < from_date:
                            continue

                        seen_urls.add(url)
                        articles.append({
                            "url": url,
                            "title": a.get("title", ""),
                            "description": a.get("description", ""),
                            "content": a.get("content", ""),
                            "source_name": a.get("source", {}).get("name", ""),
                            "source_id": a.get("source", {}).get("id"),
                            "author": a.get("author"),
                            "published_at": pub_date,
                            "url_to_image": a.get("urlToImage"),
                            "team_query": team_query,
                        })

                    print(f"     NewsAPI: {len(articles)} articles")
                else:
                    print(f"     NewsAPI error: {data.get('message', 'unknown')}")
                    # Fall through to RSS

            except ValueError as e:
                print(f"     ⚠️ NewsAPI auth error: {e}")
                use_newsapi = False  # Don't retry for other teams

            except Exception as e:
                print(f"     ⚠️ NewsAPI error: {e}")

            # Small delay between team queries to respect rate limits
            time.sleep(1)

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
    print(f"✅ Load complete!")
    print(f"   {load_info}")


# ── CLI Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_pipeline()
