"""Match Kalshi markets to NBA games and players, and read the price snapshot.

Pure functions (no internet), so they are easy to test.
"""

from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd

from src import config

NAME_SUFFIXES = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def normalize_name(name: str) -> str:
    """'Nikola Vučević' -> 'nikola vucevic', 'Jaren Jackson Jr.' -> 'jaren jackson'."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[.'’\-]", " ", text)
    text = NAME_SUFFIXES.sub(" ", text)
    return " ".join(text.split())


def player_from_title(title: str) -> str:
    """Kalshi titles: 'Cam Thomas: 25+ points' or 'Dyson Daniels records 20+ points'."""
    return re.split(r":| records ", title, maxsplit=1)[0].strip()


def line_from_strike(floor_strike: float) -> float:
    """Kalshi '25+' has floor_strike 24.5. Returns 25, or NaN if not one of our LINES."""
    line = floor_strike + 0.5
    return float(line) if line in config.LINES else np.nan


def parse_markets(markets: list[dict]) -> pd.DataFrame:
    """One row per market with the fields we need."""
    df = pd.DataFrame(markets)
    return pd.DataFrame({
        "ticker": df["ticker"],
        "source": df["source"],
        "event_key": df["event_ticker"].str.split("-").str[1],
        "kalshi_name": df["title"].map(player_from_title),
        "line": df["floor_strike"].astype(float).map(line_from_strike),
        # Kalshi times sometimes have fractions of a second, sometimes not.
        "open_time": pd.to_datetime(df["open_time"], utc=True, format="ISO8601"),
        "status": df["status"],
        "result": df["result"],
    })


def schedule_keys(schedule: pd.DataFrame) -> pd.DataFrame:
    """Add Kalshi's event key to the NBA schedule: ET date + away + home, e.g. 26MAR04ATLMIL."""
    et_date = schedule["tip_time"].dt.tz_convert("US/Eastern").dt.strftime("%y%b%d").str.upper()
    return schedule.assign(event_key=et_date + schedule["away"] + schedule["home"])


def match_players(markets: pd.DataFrame, games: pd.DataFrame) -> pd.Series:
    """NBA player_id for each market (NaN if no single match among that game's players).

    `markets` needs game_id and kalshi_name; `games` is data/games.parquet.
    """
    roster = games[["game_id", "player_id", "player_name"]].copy()
    roster["norm"] = roster["player_name"].map(normalize_name)
    # Two players with the same cleaned name in one game: too risky, no match.
    roster = roster[~roster.duplicated(["game_id", "norm"], keep=False)]
    keyed = markets[["game_id", "kalshi_name"]].assign(norm=markets["kalshi_name"].map(normalize_name))
    merged = keyed.merge(roster[["game_id", "norm", "player_id"]], on=["game_id", "norm"], how="left")
    merged.index = markets.index
    return merged["player_id"]


def snapshot(candles: list[dict], at: pd.Timestamp) -> dict:
    """Bid, ask and last trade price at time `at`, from 1-minute candlesticks.

    Candles only exist for minutes with activity, so the last candle that ends
    at or before `at` shows the order book at `at`. Prices are in dollars.
    """
    cutoff = at.timestamp()
    before = [c for c in candles if c["end_period_ts"] <= cutoff]
    empty = {"yes_bid": np.nan, "yes_ask": np.nan, "last_price": np.nan, "volume_before": 0.0}
    if not before:
        return empty
    last = before[-1]
    trades = [c["price"]["close"] for c in before if c.get("price", {}).get("close") is not None]
    return {
        "yes_bid": float(last["yes_bid"]["close"]),
        "yes_ask": float(last["yes_ask"]["close"]),
        "last_price": float(trades[-1]) if trades else np.nan,
        "volume_before": float(sum(float(c.get("volume") or 0) for c in before)),
    }
