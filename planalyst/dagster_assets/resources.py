"""
PLanalyst — Dagster: Resource Definitions

Shared resources (DB connections, API clients) for Dagster assets.
"""

from dagster import ConfigurableResource

from planalyst.config import (
    FOOTBALL_DATA_API_KEY,
    GUARDIAN_API_KEY,
    POSTGRES_CONNECTION_STRING,
)


class PostgresResource(ConfigurableResource):
    """Postgres connection string resource."""
    connection_string: str = POSTGRES_CONNECTION_STRING


class FootballAPIResource(ConfigurableResource):
    """Football-data.org API key resource."""
    api_key: str = FOOTBALL_DATA_API_KEY


class GuardianAPIResource(ConfigurableResource):
    """Guardian Open Platform key resource (GDELT needs no key)."""
    api_key: str = GUARDIAN_API_KEY
