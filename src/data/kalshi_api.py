"""Small client for Kalshi's public market-data API (no login needed).

Markets settled before Kalshi's "historical cutoff" live under /historical/...;
newer ones under the normal endpoints. This client reads both.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

import requests

from src import config

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}
HISTORICAL = "historical"
LIVE = "live"


class KalshiClient:
    def __init__(self, get: Callable = requests.get, sleep: Callable[[float], None] = time.sleep,
                 base: str = config.KALSHI_API_BASE):
        self._get = get
        self._sleep = sleep
        self._base = base

    def get_json(self, path: str, params: dict | None = None) -> dict:
        """GET with retries on timeouts, connection errors, 429 and 5xx."""
        for attempt in range(1, config.MAX_RETRIES + 1):
            try:
                resp = self._get(self._base + path, params=params, timeout=config.REQUEST_TIMEOUT_SECONDS)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as err:
                log.warning("%s: try %d/%d failed (%s)", path, attempt, config.MAX_RETRIES, err)
            else:
                if resp.status_code == 200:
                    self._sleep(config.KALSHI_REQUEST_DELAY_SECONDS)
                    return resp.json()
                if resp.status_code not in RETRY_STATUS:
                    raise RuntimeError(f"{path}: HTTP {resp.status_code} {resp.text[:200]}")
                log.warning("%s: HTTP %d, try %d/%d", path, resp.status_code, attempt, config.MAX_RETRIES)
            # Wait longer after each failed try.
            self._sleep(config.REQUEST_DELAY_SECONDS * attempt)
        raise RuntimeError(f"{path}: all {config.MAX_RETRIES} tries failed")

    def paginate(self, path: str, key: str, params: dict) -> list[dict]:
        """Follow Kalshi's cursor until the last page."""
        rows, cursor = [], None
        while True:
            page = self.get_json(path, {**params, "limit": 1000, **({"cursor": cursor} if cursor else {})})
            rows += page.get(key, [])
            cursor = page.get("cursor")
            if not cursor or not page.get(key):
                return rows

    def series(self, series: str) -> dict:
        return self.get_json(f"/series/{series}")["series"]

    def markets(self, series: str) -> list[dict]:
        """All markets of a series, historical and live, each tagged with its source."""
        hist = self.paginate("/historical/markets", "markets", {"series_ticker": series})
        live = self.paginate("/markets", "markets", {"series_ticker": series})
        seen, out = set(), []
        for source, rows in ((HISTORICAL, hist), (LIVE, live)):
            for m in rows:
                if m["ticker"] not in seen:
                    seen.add(m["ticker"])
                    out.append({**m, "source": source})
        return out

    def candles(self, series: str, ticker: str, source: str, start_ts: int, end_ts: int) -> list[dict]:
        """1-minute candlesticks (bid/ask/trade prices) between two Unix times."""
        if source == HISTORICAL:
            path = f"/historical/markets/{ticker}/candlesticks"
        else:
            path = f"/series/{series}/markets/{ticker}/candlesticks"
        params = {"start_ts": start_ts, "end_ts": end_ts, "period_interval": 1}
        return self.get_json(path, params).get("candlesticks", [])
