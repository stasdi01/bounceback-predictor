"""Brain vs baseline inside groups, on the same line (PRD 1.4, sections 6 and 7).

Analysis only. The question: does a factor help the bounce-back itself, or
does it just mark better players in every game?

For each group and line:   diff = brain hit rate - baseline hit rate.
The "all lines" row compares the brain with a baseline that has the SAME line
mix as the brain picks (weighted by brain picks per line), so a group with more
low lines does not look better just because low lines hit more often.
"""

import pandas as pd

from src.backtest.groups import apply_buckets, avg_buckets, bucket_edges, days_buckets
from src.backtest.stats import summarize

ALL_LINES = "all lines"

# factor -> (how to group it, baseline uses the same group?)
# Factors that only exist for bad games use the overall baseline on the same line.
FACTORS = {
    "consistency": ("quantile", True),
    "bb_rate_season": ("quantile", True),
    "bb_rate_all": ("quantile", True),
    "days_since_last_game": ("days", True),
    "end_of_season": ("flag", True),
    "last_game_end_of_season": ("flag", True),
    "unlucky_bad_game": ("flag", False),
    "low_minutes": ("flag", False),
    "drop_ratio": ("quantile", False),
}


def factor_labels(rp: pd.DataFrame, factor: str, kind: str) -> pd.Series:
    """Group label for every row (brain and baseline) of one line rule.

    Quantile limits come from the brain picks and are applied to all rows,
    so brain and baseline are split at the same values.
    """
    values = rp[factor]
    if kind == "quantile":
        labels = apply_buckets(values, bucket_edges(values[rp["is_brain"]]))
        if factor.startswith("bb_rate"):
            labels = labels.replace("no data", "0. no earlier bad games")
        return labels
    if kind == "days":
        return days_buckets(values)
    return values.map({True: "yes", False: "no"})


def _compare_row(brain_hits: pd.Series, base_hits: pd.Series) -> dict:
    b = summarize(brain_hits)
    base = summarize(base_hits)
    return {
        "brain_picks": b["picks"], "brain_wins": b["wins"], "brain_hit": b["hit_rate"],
        "brain_ci_low": b["ci_low"], "brain_ci_high": b["ci_high"],
        "base_picks": base["picks"], "base_hit": base["hit_rate"],
        "diff_pts": (b["hit_rate"] - base["hit_rate"]) * 100,
        "small_sample": b["small_sample"],
    }


def compare_group(rp: pd.DataFrame, in_group: pd.Series, same_group: bool) -> list[dict]:
    """Rows per line, plus an "all lines" row, for one group."""
    brain = rp[in_group & rp["is_brain"]]
    base_pool = rp[in_group] if same_group else rp
    rows, expected, base_n = [], 0.0, 0
    for line in sorted(brain["line"].unique()):
        base_hits = base_pool.loc[base_pool["line"] == line, "hit"]
        brain_hits = brain.loc[brain["line"] == line, "hit"]
        row = _compare_row(brain_hits, base_hits)
        rows.append({"line": f"{line}+", **row})
        expected += row["brain_picks"] * row["base_hit"]
        base_n += row["base_picks"]
    if rows:
        total = _compare_row(brain["hit"], pd.Series([], dtype=bool))
        total["base_picks"] = base_n
        total["base_hit"] = expected / total["brain_picks"]
        total["diff_pts"] = (total["brain_hit"] - total["base_hit"]) * 100
        rows.append({"line": ALL_LINES, **total})
    return rows


def compare_by(rp: pd.DataFrame, view: str, factor: str, labels: pd.Series, same_group: bool) -> list[dict]:
    rows = []
    for group in sorted(labels[rp["is_brain"]].unique()):
        for r in compare_group(rp, labels == group, same_group):
            rows.append({"view": view, "factor": factor, "group": group,
                         "baseline": "same group" if same_group else "overall", **r})
    return rows


def build_comparisons(picks: pd.DataFrame) -> pd.DataFrame:
    """Sections 6 (factor vs baseline) and 7 (by season average group)."""
    rows = []
    for rule, rp in picks.groupby("line_rule", sort=True):
        rule_rows = []
        for factor, (kind, same_group) in FACTORS.items():
            labels = factor_labels(rp, factor, kind)
            rule_rows += compare_by(rp, "6_factor_vs_baseline", factor, labels, same_group)
        rule_rows += compare_by(rp, "7_by_avg_group", "season average", avg_buckets(rp["avg_pts"]), True)
        rows += [{"line_rule": rule, **r} for r in rule_rows]
    return pd.DataFrame(rows)


def format_comparison(rows: pd.DataFrame) -> str:
    """One text table per factor."""
    def pct(v):
        return "-" if pd.isna(v) else f"{v:.1%}"

    parts = []
    for factor, fr in rows.groupby("factor", sort=False):
        parts.append(f"\n{factor} (baseline = {fr['baseline'].iloc[0]}, same line)")
        table = pd.DataFrame({
            "group": fr["group"],
            "line": fr["line"],
            "brain picks": fr["brain_picks"],
            "brain hit": [pct(v) for v in fr["brain_hit"]],
            "brain 95% range": [
                "-" if pd.isna(lo) else f"{lo:.1%} to {hi:.1%}" for lo, hi in zip(fr["brain_ci_low"], fr["brain_ci_high"])
            ],
            "base picks": fr["base_picks"],
            "base hit": [pct(v) for v in fr["base_hit"]],
            "diff": ["-" if pd.isna(v) else f"{v:+.1f}" for v in fr["diff_pts"]],
            "note": fr["small_sample"].map({True: "*", False: ""}),
        })
        parts.append(table.to_string(index=False))
    return "\n".join(parts)
