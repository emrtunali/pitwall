"""Minimal OpenF1 client: rate limited, retrying, with an on-disk JSON cache.

OpenF1 (https://openf1.org) serves historical F1 timing data for free with a limit of
3 requests per second and 30 per minute. Everything we fetch is cached under ``data/cache`` so that
rebuilding the site never hits the API twice for the same query.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

BASE_URL = "https://api.openf1.org/v1"


class OpenF1:
    # The free tier allows 3 requests/s and 30 requests/min; stay just under the per-minute cap.
    def __init__(self, cache_dir: Path, min_interval: float = 2.1, client: httpx.Client | None = None):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.client = client or httpx.Client(timeout=120, headers={"User-Agent": "pitwall/0.1"})
        self._last = 0.0

    def _cache_path(self, endpoint: str, query: str) -> Path:
        digest = hashlib.sha1(query.encode()).hexdigest()[:16]
        return self.cache_dir / endpoint / f"{digest}.json.gz"

    def get(self, endpoint: str, cache: bool = True, **params) -> list[dict]:
        """GET an endpoint. Finished-session data never changes, so it is cached forever; pass
        ``cache=False`` for things that do change (the season calendar, cancellations)."""
        # OpenF1 filters such as ``date>`` are written as part of the key: get("location", **{"date>": "..."})
        query = urlencode(sorted(params.items()), safe=":<>")
        path = self._cache_path(endpoint, query)
        if cache and path.exists():
            return json.loads(gzip.decompress(path.read_bytes()))
        url = f"{BASE_URL}/{endpoint}?{query}"
        for attempt in range(6):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            resp = self.client.get(url)
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(min(60, 5 * 2**attempt))
                continue
            if resp.status_code == 404:
                data: list[dict] = []
                break
            resp.raise_for_status()
            data = resp.json()
            break
        else:
            raise RuntimeError(f"OpenF1 request kept failing: {url}")
        if not cache or not data:
            return data  # never cache an empty answer: the data may simply not be published yet
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(json.dumps(data).encode(), compresslevel=6))
        return data
