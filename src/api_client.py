"""
EPL Analytics — FPL API Client

Provides a resilient HTTP client for the Fantasy Premier League REST API
with automatic retries, exponential backoff, and structured logging.
"""

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config import api_config

logger = logging.getLogger(__name__)


class FPLAPIError(Exception):
    """Raised when the FPL API returns a non-200 response after retries."""

    def __init__(self, url: str, status_code: int, message: str = "") -> None:
        self.url = url
        self.status_code = status_code
        super().__init__(
            f"FPL API error: {status_code} for {url}. {message}"
        )


class FPLClient:
    """HTTP client for Fantasy Premier League API endpoints.

    Uses requests.Session with retry adapter for resilience.

    Usage:
        client = FPLClient()
        data = client.get_bootstrap_static()
    """

    def __init__(self, config: Any = None) -> None:
        """Initialise client with optional config override (useful for testing).

        Args:
            config: APIConfig instance. Defaults to global api_config.
        """
        self._config = config or api_config
        self._session = self._build_session()

    def _build_session(self) -> requests.Session:
        """Build a requests.Session with retry strategy."""
        session = requests.Session()
        retry_strategy = Retry(
            total=self._config.max_retries,
            backoff_factor=self._config.retry_backoff,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({
            "User-Agent": "EPL-Analytics-Pipeline/1.0",
            "Accept": "application/json",
        })
        return session

    def _get(self, url: str) -> dict:
        """Execute GET request with logging and error handling.

        Args:
            url: Full URL to request.

        Returns:
            Parsed JSON response as dict.

        Raises:
            FPLAPIError: If response status is not 200 after retries.
        """
        logger.info("Requesting: %s", url)
        try:
            response = self._session.get(
                url, timeout=self._config.request_timeout
            )
            response.raise_for_status()
            logger.info(
                "Success: %s (%d bytes)", url, len(response.content)
            )
            return response.json()
        except requests.exceptions.HTTPError as exc:
            logger.error("HTTP error for %s: %s", url, exc)
            raise FPLAPIError(
                url=url,
                status_code=exc.response.status_code if exc.response else 0,
                message=str(exc),
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            logger.error("Connection error for %s: %s", url, exc)
            raise FPLAPIError(url=url, status_code=0, message=str(exc)) from exc
        except requests.exceptions.Timeout as exc:
            logger.error("Timeout for %s: %s", url, exc)
            raise FPLAPIError(url=url, status_code=408, message=str(exc)) from exc

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_bootstrap_static(self) -> dict:
        """Fetch full bootstrap-static data (players, teams, events).

        Returns:
            Dict with keys: elements, teams, events, element_types, etc.
        """
        url = f"{self._config.base_url}{self._config.bootstrap_endpoint}"
        return self._get(url)

    def get_fixtures(self) -> list[dict]:
        """Fetch all fixtures for the current season.

        Returns:
            List of fixture dicts.
        """
        url = f"{self._config.base_url}{self._config.fixtures_endpoint}"
        return self._get(url)

    def get_event_live(self, gameweek: int) -> dict:
        """Fetch live player stats for a specific gameweek.

        Args:
            gameweek: Gameweek number (1-38).

        Returns:
            Dict with key 'elements' containing per-player stats.

        Raises:
            ValueError: If gameweek is out of range.
        """
        if not 1 <= gameweek <= 38:
            raise ValueError(f"Gameweek must be 1-38, got {gameweek}")
        url = self._config.event_live_url(gameweek)
        return self._get(url)

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()
        logger.info("FPL client session closed.")

    def __enter__(self) -> "FPLClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
