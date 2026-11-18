"""Backtest report (PRD step 1.4).

`build_summary(picks)` returns one long table: one row per
(line rule, section, group, subset) with the stats from stats.summarize.
`format_report(...)` turns it into plain text.
"""

import numpy as np
import pandas as pd

from src import config
from src.backtest.stats import summarize

SECTIONS = {
    "1_overview": "1. Brain vs baseline",
    "2_by_line": "2. By line (brain vs baseline on the same line)",
    "3_bad_game_reason": "3. By bad-game reason (brain picks)",
    "4_strength": "4. By strength factor (brain picks)",
    "5_by_season": "5. By season",
}

REASON_FLAGS = ["low_minutes", "blowout", "unlucky_bad_game", "end_of_season", "last_game_end_of_season"]
QUANTILE_FACTORS = ["bb_rate_season", "bb_rate_all", "consistency", "drop_ratio"]
BUCKET_NAMES = {1: ["all"], 2: ["low", "high"], 3: ["low", "mid", "high"]}


# --- grouping helpers -------------------------------------------------------

def quantile_buckets(values: pd.Series, n: int = config.STRENGTH_BUCKETS) -> pd.Series:
    """Split values into n equal-size groups, labelled with their value range.

    Missing values get "no data". If many values are equal, fewer groups may result.
    """
    labels = pd.Series("no data", index=values.index, dtype=object)
    present = values.dropna()
    if present.empty:
        return labels
    codes, edges = pd.qcut(present, q=n, labels=False, retbins=True, duplicates="drop")
    names = BUCKET_NAMES.get(len(edges) - 1, [f"q{i + 1}" for i in range(len(edges) - 1)])
    for code, name in enumerate(names):
        labels[codes.index[codes == code]] = f"{code + 1}. {name} ({edges[code]:.2f} to {edges[code + 1]:.2f})"
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


# --- sections ---------------------------------------------------------------

def _rows(section: str, group: str, subset: str, hits: pd.Series) -> dict:
    return {"section": section, "group": group, "subset": subset, **summarize(hits)}


def overview_rows(picks: pd.DataFrame) -> list[dict]:
    brain = picks[picks["is_brain"]]
    s = "1_overview"
    return [
        _rows(s, "all", "brain", brain["hit"]),
        _rows(s, "normal", "brain", brain.loc[brain["confidence"] == "normal", "hit"]),
        _rows(s, "strong", "brain", brain.loc[brain["confidence"] == "strong", "hit"]),
        _rows(s, "all", "baseline", picks["hit"]),
        _rows(s, "non-bad games", "baseline", picks.loc[~picks["is_brain"], "hit"]),
    ]


def grouped_rows(section: str, picks: pd.DataFrame, by: pd.Series, both: bool) -> list[dict]:
    """Stats per group of `by`, for brain picks (and baseline if both=True)."""
    rows = []
    for group in sorted(by.unique()):
        in_group = by == group
        rows.append(_rows(section, str(group), "brain", picks.loc[in_group & picks["is_brain"], "hit"]))
        if both:
            rows.append(_rows(section, str(group), "baseline", picks.loc[in_group, "hit"]))
    return rows


def reason_rows(picks: pd.DataFrame) -> list[dict]:
    brain = picks[picks["is_brain"]]
    rows = []
    for flag in REASON_FLAGS:
        labels = brain[flag].map({True: f"{flag} = yes", False: f"{flag} = no"})
        rows += grouped_rows("3_bad_game_reason", brain, labels, both=False)
    return rows


def strength_rows(picks: pd.DataFrame) -> list[dict]:
    brain = picks[picks["is_brain"]]
    rows = []
    for factor in QUANTILE_FACTORS:
        labels = quantile_buckets(brain[factor])
        if factor.startswith("bb_rate"):
            labels = labels.replace("no data", "0. no earlier bad games")
        rows += grouped_rows("4_strength", brain, factor + ": " + labels, both=False)
    rows += grouped_rows("4_strength", brain, "days_since_last_game: " + days_buckets(brain["days_since_last_game"]), both=False)
    return rows


def build_summary(picks: pd.DataFrame) -> pd.DataFrame:
    """All report sections for every line rule, as one long table."""
    rows = []
    for rule, rp in picks.groupby("line_rule", sort=True):
        rule_rows = (
            overview_rows(rp)
            + grouped_rows("2_by_line", rp, rp["line"].astype(str) + "+", both=True)
            + reason_rows(rp)
            + strength_rows(rp)
            + grouped_rows("5_by_season", rp, rp["season"], both=True)
        )
        rows += [{"line_rule": rule, **r} for r in rule_rows]
    return pd.DataFrame(rows)


# --- examples and text ------------------------------------------------------

def pick_reason(row: pd.Series) -> str:
    """Short reason text, e.g. "avg 23.4, last game 9 pts, 2 bad games in a row"."""
    text = f"avg {row['avg_pts']:.1f}, last game {row['last_pts']:.0f} pts"
    if row["confidence"] == "strong":
        text += ", 2 bad games in a row"
    return text


def example_picks(picks: pd.DataFrame, rule: str) -> pd.DataFrame:
    """A fixed random sample of brain picks for one line rule."""
    brain = picks[(picks["line_rule"] == rule) & picks["is_brain"]]
    sample = brain.sample(min(config.REPORT_EXAMPLE_PICKS, len(brain)), random_state=config.REPORT_SEED)
    sample = sample.sort_values("game_date")
    return pd.DataFrame({
        "date": sample["game_date"].dt.strftime("%Y-%m-%d"),
        "player": sample["player_name"],
        "team": sample["team_abbreviation"],
        "line": sample["line"].astype(str) + "+",
        "confidence": sample["confidence"],
        "reason": sample.apply(pick_reason, axis=1),
        "pts": sample["pts"],
        "hit": sample["hit"].map({True: "WIN", False: "loss"}),
    })


def _fmt(value: float, pattern: str) -> str:
    """Format a number, or "-" when it is missing (empty group)."""
    return "-" if pd.isna(value) else pattern.format(value)


def _format_table(rows: pd.DataFrame) -> str:
    """Readable columns for one section."""
    table = pd.DataFrame({
        "group": rows["group"],
        "subset": rows["subset"],
        "picks": rows["picks"],
        "wins": rows["wins"],
        "hit rate": [_fmt(v, "{:.1%}") for v in rows["hit_rate"]],
        "95% range": [
            "-" if pd.isna(lo) else f"{lo:.1%} to {hi:.1%}" for lo, hi in zip(rows["ci_low"], rows["ci_high"])
        ],
        "max price": [_fmt(v, "{:.1f}c") for v in rows["max_price_cents"]],
        "min odds": [_fmt(v, "{:.2f}") for v in rows["min_odds"]],
        "note": rows["small_sample"].map({True: "*", False: ""}),
    })
    return table.to_string(index=False)


def format_report(summary: pd.DataFrame, picks: pd.DataFrame) -> str:
    seasons = ", ".join(sorted(picks["season"].unique()))
    lines = [
        "BOUNCEBACK PREDICTOR: BACKTEST REPORT",
        f"Seasons: {seasons}",
        f"* = fewer than {config.MIN_RELIABLE_PICKS} picks (small sample, do not trust)",
        "max price = hit rate x 100 - fee buffer; min odds = 100 / max price",
        "",
    ]
    for rule in sorted(summary["line_rule"].unique()):
        lines += ["=" * 100, f"LINE RULE: {rule}", "=" * 100]
        for key, title in SECTIONS.items():
            rows = summary[(summary["line_rule"] == rule) & (summary["section"] == key)]
            lines += ["", title, "-" * len(title), _format_table(rows)]
        lines += ["", "6. Example picks", "----------------", example_picks(picks, rule).to_string(index=False), ""]
    return "\n".join(lines)
