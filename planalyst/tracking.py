"""
PLanalyst — MLflow tracking helpers.

Uses a local file store by default so experiment logs persist even when
the optional MLflow server on port 5000 is not running.
"""

import os
from pathlib import Path

from planalyst.config import PROJECT_ROOT

DEFAULT_FILE_STORE = (Path(PROJECT_ROOT) / "mlruns").resolve()


def configure_mlflow():
    """Configure MLflow tracking URI. Prefer a reachable HTTP server, else files."""
    import mlflow

    file_uri = DEFAULT_FILE_STORE.as_uri()
    env_uri = os.getenv("MLFLOW_TRACKING_URI", "").strip()

    if env_uri.startswith("http"):
        mlflow.set_tracking_uri(env_uri)
        try:
            mlflow.search_experiments(max_results=1)
            return mlflow
        except Exception:
            print(f"  MLflow server at {env_uri} unreachable; using file store {file_uri}")

    mlflow.set_tracking_uri(env_uri if env_uri.startswith("file:") else file_uri)
    DEFAULT_FILE_STORE.mkdir(parents=True, exist_ok=True)
    return mlflow
