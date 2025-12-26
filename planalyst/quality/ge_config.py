"""
PLanalyst — Great Expectations: Configuration & Context Setup

Sets up the GE data context for validating bronze layer data in PostgreSQL.
"""

from typing import Any

import great_expectations as gx
from planalyst.config import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)


def get_context():
    """
    Create and return a GX ephemeral data context connected to our Postgres.

    Uses the GX 1.0+ API with fluent datasource configuration.
    """
    context = gx.get_context(mode="ephemeral")

    datasource_name = "planalyst_postgres"
    try:
        context.data_sources.get(datasource_name)
    except (KeyError, Exception):
        connection_string = (
            f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
            f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
        )
        context.data_sources.add_postgres(
            name=datasource_name,
            connection_string=connection_string,
        )

    return context


def get_datasource(context) -> Any:
    """Get the Postgres datasource from the context."""
    return context.data_sources.get("planalyst_postgres")


def get_or_create_table_asset(context, asset_name: str, table_name: str, schema_name: str):
    """Return an existing fluent table asset, or create it."""
    datasource = get_datasource(context)
    try:
        return datasource.get_asset(asset_name)
    except Exception:
        return datasource.add_table_asset(
            name=asset_name,
            table_name=table_name,
            schema_name=schema_name,
        )


def get_or_create_batch_definition(data_asset, name: str):
    """Return an existing whole-table batch definition, or create it."""
    try:
        return data_asset.get_batch_definition(name)
    except Exception:
        return data_asset.add_batch_definition_whole_table(name)
