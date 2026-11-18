"""Hit rate statistics for the backtest report (PRD step 1.4)."""

import math

import pandas as pd

from src import config


def wilson_range(wins: int, picks: int, z: float = config.CI_Z) -> tuple[float, float]:
    """95% range of a hit rate (Wilson method).

    Better than "rate +/- 1.96 * standard error" for small groups and for hit
    rates near 0% or 100%, where the simple method gives impossible ranges.
    """
    if picks == 0:
        return math.nan, math.nan
    rate = wins / picks
    denom = 1 + z**2 / picks
    center = (rate + z**2 / (2 * picks)) / denom
    half = z * math.sqrt(rate * (1 - rate) / picks + z**2 / (4 * picks**2)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def max_price_cents(hit_rate: float) -> float:
    """PRD: max_price_cents = hit_rate * 100 - FEE_BUFFER_CENTS."""
    return hit_rate * 100 - config.FEE_BUFFER_CENTS


def min_odds(max_price: float) -> float:
    """Decimal odds that match the max price (100 / price). NaN if price <= 0."""
    return 100 / max_price if max_price > 0 else math.nan


def summarize(hits: pd.Series) -> dict:
    """Picks, wins, hit rate, 95% range, max price and min odds for one group."""
    picks = int(len(hits))
    wins = int(hits.sum())
    rate = wins / picks if picks else math.nan
    low, high = wilson_range(wins, picks)
    price = max_price_cents(rate) if picks else math.nan
    return {
        "picks": picks,
        "wins": wins,
        "hit_rate": rate,
        "ci_low": low,
        "ci_high": high,
        "max_price_cents": price,
        "min_odds": min_odds(price) if picks else math.nan,
        "small_sample": picks < config.MIN_RELIABLE_PICKS,
    }
