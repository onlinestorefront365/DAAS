import logging
import time
from collections.abc import Iterator
from datetime import date
from typing import Any

import httpx

log = logging.getLogger(__name__)


class SocrataClient:
    """Pages a Socrata SODA 2.x dataset filtered on a date column, oldest first."""

    def __init__(
        self,
        domain: str,
        dataset_id: str,
        date_field: str,
        *,
        app_token: str = "",
        page_size: int = 5000,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 4,
    ) -> None:
        self.url = f"https://{domain}/resource/{dataset_id}.json"
        self.date_field = date_field
        self.page_size = page_size
        self.max_retries = max_retries
        headers = {"X-App-Token": app_token} if app_token else {}
        self._client = httpx.Client(timeout=timeout, headers=headers, transport=transport)

    def fetch_since(self, since: date) -> Iterator[dict[str, Any]]:
        offset = 0
        while True:
            params = {
                "$where": f"{self.date_field} >= '{since.isoformat()}T00:00:00'",
                # :id breaks ties so offset paging is stable across requests.
                "$order": f"{self.date_field} ASC, :id ASC",
                "$limit": str(self.page_size),
                "$offset": str(offset),
            }
            rows = self._get(params)
            yield from rows
            if len(rows) < self.page_size:
                return
            offset += self.page_size

    def _get(self, params: dict[str, str]) -> list[dict[str, Any]]:
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.get(self.url, params=params)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise httpx.HTTPStatusError("retryable", request=resp.request, response=resp)
                resp.raise_for_status()
                return resp.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                retryable = isinstance(exc, httpx.TransportError) or (
                    exc.response.status_code == 429 or exc.response.status_code >= 500
                )
                if not retryable or attempt == self.max_retries:
                    raise
                delay = 2 ** (attempt + 1)
                log.warning("socrata %s failed (%s); retrying in %ss", self.url, exc, delay)
                time.sleep(delay)
        raise AssertionError("unreachable")
