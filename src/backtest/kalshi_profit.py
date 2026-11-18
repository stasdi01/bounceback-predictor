"""Backtest profit with real Kalshi prices (PRD step 1.7, report section 9).

For each pick that has a Kalshi market on its line:
- price = ask at tip-off - 60 minutes (what we would really pay)
- skip (and count) if there is no quote or ask >= KALSHI_NO_SELLER_ASK
- buy C contracts, pay C x ask + taker fee; each pick stakes 1 unit (price + fee)
- profit per pick in units: win = (C - cost) / cost, loss = -1
The mid price is only shown for reference.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src import config
from src.backtest.groups import avg_buckets

NO_MARKET, NO_QUOTE, PRICED = "no market", "no quote", "priced"
PRICE_COLUMNS = ["yes_bid", "yes_ask", "last_price", "result", "fee_multiplier"]


def taker_fee(price, contracts, multiplier, rate=config.KALSHI_TAKER_FEE_RATE):
    """Kalshi taker fee in dollars: round up to the cent of M x rate x C x P x (1 - P).

    Works on numbers and on pandas Series. The tiny rounding before ceil()
    stops float noise (e.g. 1.0000000001 cents) from adding a whole cent.
    """
    raw_cents = multiplier * rate * contracts * price * (1 - price) * 100
    return np.ceil(np.round(raw_cents, 6)) / 100


def attach_prices(picks: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """Picks in the Kalshi period, with prices and a price_status."""
    first_date = picks.loc[picks["game_id"].isin(prices["game_id"]), "game_date"].min()
    window = picks[picks["season"].isin(config.KALSHI_SEASONS) & (picks["game_date"] >= first_date)]
    keyed = prices[["game_id", "player_id", "line"] + PRICE_COLUMNS]
    df = window.merge(keyed, on=["game_id", "player_id", "line"], how="left", indicator="_market")
    ask = df["yes_ask"]
    df["price_status"] = np.select(
        [df["_market"] == "left_only", ask.isna() | (ask <= 0) | (ask >= config.KALSHI_NO_SELLER_ASK)],
        [NO_MARKET, NO_QUOTE],
        default=PRICED,
    )
    return df.drop(columns="_market")


def add_profit(df: pd.DataFrame) -> pd.DataFrame:
    """Odds, fee, cost and profit per pick (only meaningful for priced rows)."""
    df = df.copy()
    priced = df["price_status"] == PRICED
    ask = df["yes_ask"].where(priced)
    contracts = config.KALSHI_BACKTEST_CONTRACTS
    df["odds"] = 1 / ask
    df["mid"] = ((df["yes_bid"] + df["yes_ask"]) / 2).where(priced & (df["yes_bid"] > 0))
    df["fee"] = taker_fee(ask, contracts, df["fee_multiplier"])
    df["cost"] = contracts * ask + df["fee"]
    df["profit_units"] = np.where(df["hit"], (contracts - df["cost"]) / df["cost"], -1.0)
    df.loc[~priced, "profit_units"] = np.nan
    df["passes_min_odds"] = priced & (df["odds"] >= config.MIN_ODDS)
    return df


def result_mismatches(df: pd.DataFrame) -> int:
    """Priced picks where Kalshi's result disagrees with our hit (data check)."""
    priced = df[(df["price_status"] == PRICED) & df["result"].isin(["yes", "no"])]
    return int(((priced["result"] == "yes") != priced["hit"]).sum())


def money_stats(rows: pd.DataFrame) -> dict:
    """Hit rate vs price, and ROI (1 unit per pick) with a 95% range."""
    n = len(rows)
    if n == 0:
        return {"picks": 0, "wins": 0, "hit_rate": np.nan, "avg_ask": np.nan, "edge_pts": np.nan,
                "avg_mid": np.nan, "avg_odds": np.nan, "roi": np.nan, "roi_ci_low": np.nan,
                "roi_ci_high": np.nan, "profit_units": 0.0, "small_sample": True}
    profit = rows["profit_units"]
    half = config.CI_Z * profit.std(ddof=1) / math.sqrt(n) if n > 1 else np.nan
    hit_rate = rows["hit"].mean()
    return {
        "picks": n,
        "wins": int(rows["hit"].sum()),
        "hit_rate": hit_rate,
        "avg_ask": rows["yes_ask"].mean(),  # = average price-implied probability
        "edge_pts": (hit_rate - rows["yes_ask"].mean()) * 100,
        "avg_mid": rows["mid"].mean(),
        "avg_odds": rows["odds"].mean(),
        "roi": profit.mean(),
        "roi_ci_low": profit.mean() - half,
        "roi_ci_high": profit.mean() + half,
        "profit_units": profit.sum(),
        "small_sample": n < config.MIN_RELIABLE_PICKS,
    }


def coverage_rows(df: pd.DataFrame) -> list[dict]:
    """How many picks have a usable price, per line rule and subset."""
    rows = []
    for rule, rp in df.groupby("line_rule", sort=True):
        for subset, part in (("brain", rp[rp["is_brain"]]), ("baseline", rp)):
            status = part["price_status"]
            rows.append({
                "line_rule": rule, "subset": subset, "picks_in_period": len(part),
                "no_market": int((status == NO_MARKET).sum()), "no_quote": int((status == NO_QUOTE).sum()),
                "priced": int((status == PRICED).sum()), "priced_odds_ok": int(part["passes_min_odds"].sum()),
            })
    return rows


def _group_rows(rule, odds_filter, part, view, labels, subset) -> list[dict]:
    return [
        {"line_rule": rule, "odds_filter": odds_filter, "view": view, "group": str(g), "subset": subset,
         **money_stats(part[labels == g])}
        for g in sorted(labels.unique())
    ]


def build_kalshi_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Section 9 table: brain vs baseline, for all priced picks and with minimum odds."""
    priced = df[df["price_status"] == PRICED]
    filters = {"all priced": priced, f"odds >= {config.MIN_ODDS:.2f}": priced[priced["passes_min_odds"]]}
    rows = []
    for rule in sorted(priced["line_rule"].unique()):
        for name, frame in filters.items():
            rp = frame[frame["line_rule"] == rule]
            brain, base = rp[rp["is_brain"]], rp
            one = lambda part: pd.Series("all", index=part.index)  # noqa: E731
            rows += _group_rows(rule, name, brain, "overall", one(brain), "brain")
            rows += _group_rows(rule, name, base, "overall", one(base), "baseline")
            rows += _group_rows(rule, name, base[~base["is_brain"]], "overall",
                                one(base[~base["is_brain"]]), "baseline non-bad games")
            rows += _group_rows(rule, name, brain, "confidence", brain["confidence"], "brain")
            for subset, part in (("brain", brain), ("baseline", base)):
                rows += _group_rows(rule, name, part, "line", part["line"].astype(str) + "+", subset)
                rows += _group_rows(rule, name, part, "season average", avg_buckets(part["avg_pts"]), subset)
            for flag in ("unlucky_bad_game", "low_minutes"):
                rows += _group_rows(rule, name, brain, flag, brain[flag].map({True: "yes", False: "no"}), "brain")
    return pd.DataFrame(rows)


# --- text -------------------------------------------------------------------

def _pct(v, pattern="{:.1%}"):
    return "-" if pd.isna(v) else pattern.format(v)


def _format_money_table(rows: pd.DataFrame) -> str:
    table = pd.DataFrame({
        "view": rows["view"], "group": rows["group"], "subset": rows["subset"],
        "picks": rows["picks"], "hit rate": [_pct(v) for v in rows["hit_rate"]],
        "avg ask": [_pct(v) for v in rows["avg_ask"]],
        "edge": ["-" if pd.isna(v) else f"{v:+.1f}" for v in rows["edge_pts"]],
        "avg mid": [_pct(v) for v in rows["avg_mid"]],
        "avg odds": [_pct(v, "{:.2f}") for v in rows["avg_odds"]],
        "ROI": [_pct(v, "{:+.1%}") for v in rows["roi"]],
        "ROI 95% range": ["-" if pd.isna(lo) else f"{lo:+.1%} to {hi:+.1%}"
                          for lo, hi in zip(rows["roi_ci_low"], rows["roi_ci_high"])],
        "units": [f"{v:+.1f}" for v in rows["profit_units"]],
        "note": rows["small_sample"].map({True: "*", False: ""}),
    })
    return table.to_string(index=False)


def format_kalshi_section(result: "KalshiResult", rule: str) -> str:
    summary, period, mismatches = result.summary, result.period, result.mismatches
    cov = result.coverage[result.coverage["line_rule"] == rule].drop(columns="line_rule")
    lines = [
        f"Period: {period}. Price = ask at tip-off - {config.PRICE_SNAPSHOT_MINUTES_BEFORE} min, "
        f"Kalshi taker fee included ({config.KALSHI_BACKTEST_CONTRACTS} contracts per pick), 1 unit per pick.",
        "edge = hit rate - avg ask (the price-implied probability), in percentage points.",
        f"Skipped: no market on the line, or no quote / ask >= {config.KALSHI_NO_SELLER_ASK:.2f}. "
        f"Kalshi result vs our hit mismatches: {mismatches}.",
        "",
        "Coverage:",
        cov.to_string(index=False),
    ]
    for odds_filter, rows in summary[summary["line_rule"] == rule].groupby("odds_filter", sort=False):
        lines += ["", f"Picks: {odds_filter}", _format_money_table(rows)]
    return "\n".join(lines)


@dataclass
class KalshiResult:
    summary: pd.DataFrame
    coverage: pd.DataFrame
    mismatches: int
    period: str


def kalshi_analysis(picks: pd.DataFrame, prices: pd.DataFrame) -> KalshiResult:
    """Section 9 numbers for all picks that fall in the Kalshi period."""
    df = add_profit(attach_prices(picks, prices))
    period = f"{df['game_date'].min():%Y-%m-%d} to {df['game_date'].max():%Y-%m-%d}"
    return KalshiResult(build_kalshi_summary(df), pd.DataFrame(coverage_rows(df)), result_mismatches(df), period)
