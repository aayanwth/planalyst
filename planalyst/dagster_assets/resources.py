"""
PLanalyst — Dagster: Resource Definitions

Shared resources (DB connections, API clients) for Dagster assets.
"""

from dagster import ConfigurableResource

from planalyst.config import (
    FOOTBALL_DATA_API_KEY,
    NEWS_API_KEY,
    POSTGRES_CONNECTION_STRING,
)


class PostgresResource(ConfigurableResource):
    """Postgres connection string resource."""
    connection_string: str = POSTGRES_CONNECTION_STRING


class FootballAPIResource(ConfigurableResource):
    """Football-data.org API key resource."""
    api_key: str = FOOTBALL_DATA_API_KEY


class NewsAPIResource(ConfigurableResource):
    """NewsAPI key resource."""
    api_key: str = NEWS_API_KEY
