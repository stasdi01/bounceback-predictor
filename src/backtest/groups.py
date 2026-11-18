"""Grouping helpers for the backtest report: equal-size groups, days, season average."""

import numpy as np
import pandas as pd

from src import config

BUCKET_NAMES = {1: ["all"], 2: ["low", "high"], 3: ["low", "mid", "high"]}


def bucket_edges(values: pd.Series, n: int = config.STRENGTH_BUCKETS) -> np.ndarray:
    """Edges that split `values` into n equal-size groups.

    If many values are equal, edges merge and fewer groups result.
    Returns an empty array if there are no values.
    """
    present = values.dropna()
    if present.empty:
        return np.array([])
    return np.unique(np.quantile(present, np.linspace(0, 1, n + 1)))


def apply_buckets(values: pd.Series, edges: np.ndarray) -> pd.Series:
    """Label values with the groups from `bucket_edges`.

    The outer groups are open ("to x", "above y"), so values from another set of
    rows (e.g. baseline rows, using edges from brain picks) always get a group.
    Missing values get "no data".
    """
    labels = pd.Series("no data", index=values.index, dtype=object)
    present = values.notna()
    if len(edges) < 2:  # no values, or all values equal
        labels[present] = "1. all"
        return labels
    inner = list(edges[1:-1])
    codes = pd.cut(values[present], [-np.inf] + inner + [np.inf], labels=False, right=True)
    k = len(inner) + 1
    names = BUCKET_NAMES.get(k, [f"q{i + 1}" for i in range(k)])
    for code, name in enumerate(names):
        if k == 1:
            text = "all"
        elif code == 0:
            text = f"{name} (to {inner[0]:.2f})"
        elif code == k - 1:
            text = f"{name} (above {inner[-1]:.2f})"
        else:
            text = f"{name} ({inner[code - 1]:.2f} to {inner[code]:.2f})"
        labels[codes.index[codes == code]] = f"{code + 1}. {text}"
    return labels


def quantile_buckets(values: pd.Series, n: int = config.STRENGTH_BUCKETS) -> pd.Series:
    """Equal-size groups of `values`, labelled with their value range."""
    return apply_buckets(values, bucket_edges(values, n))


def avg_buckets(avg_pts: pd.Series, edges=config.AVG_GROUPS) -> pd.Series:
    """Season average groups, e.g. 14-19.9 / 20-24.9 / 25-29.9."""
    labels = pd.Series("other", index=avg_pts.index, dtype=object)
    for low, high in zip(edges[:-1], edges[1:]):
        labels[(avg_pts >= low) & (avg_pts < high)] = f"avg {low}-{high - 0.1:.1f}"
    return labels


def days_buckets(days: pd.Series, bins=config.DAYS_SINCE_BINS) -> pd.Series:
    """Fixed groups for days since last game, e.g. 1 / 2-3 / 4-7 / 8+."""
    labels = pd.Series("no data", index=days.index, dtype=object)
    edges = list(bins) + [np.inf]
    for low, high in zip(edges[:-1], edges[1:]):
        rows = (days >= low) & (days < high)
        if high == np.inf:
            name = f"{low}+"
        elif high - low == 1:
            name = f"{low}"
        else:
            name = f"{low}-{high - 1}"
        labels[rows] = f"{name} days"
    return labels
