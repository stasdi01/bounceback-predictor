"""Tests for src/backtest/stats.py, report.py and run.py."""

import math

import numpy as np
import pandas as pd
import pytest

from src import config
from src.backtest import run
from src.backtest.compare import build_comparisons
from src.backtest.groups import avg_buckets, days_buckets, quantile_buckets
from src.backtest.report import build_summary, format_report, pick_reason
from src.backtest.stats import max_price_cents, min_odds, summarize, wilson_range
from src.brain.features import build_features
from src.brain.picks import make_picks
from tests.helpers import synthetic_games


# --- stats ------------------------------------------------------------------

def test_wilson_known_value():
    low, high = wilson_range(8, 10)
    assert low == pytest.approx(0.4902, abs=1e-3)
    assert high == pytest.approx(0.9433, abs=1e-3)


def test_wilson_edge_cases():
    assert wilson_range(0, 10)[0] == 0.0
    assert wilson_range(10, 10)[1] == 1.0
    assert 0.6 < wilson_range(10, 10)[0] < 1.0  # never a range above 100%
    assert all(math.isnan(v) for v in wilson_range(0, 0))


def test_wilson_gets_narrower_with_more_picks():
    small = wilson_range(75, 100)
    big = wilson_range(750, 1000)
    assert (big[1] - big[0]) < (small[1] - small[0])


def test_max_price_and_min_odds():
    assert max_price_cents(0.75) == pytest.approx(75 - config.FEE_BUFFER_CENTS)
    assert min_odds(73.0) == pytest.approx(100 / 73)
    assert math.isnan(min_odds(-2.0))


def test_summarize():
    s = summarize(pd.Series([True, True, True, False]))
    assert (s["picks"], s["wins"], s["hit_rate"]) == (4, 3, 0.75)
    assert s["small_sample"]
    big = summarize(pd.Series([True] * config.MIN_RELIABLE_PICKS))
    assert not big["small_sample"]


def test_summarize_empty_group():
    s = summarize(pd.Series([], dtype=bool))
    assert s["picks"] == 0 and math.isnan(s["hit_rate"]) and math.isnan(s["min_odds"])


# --- grouping helpers -------------------------------------------------------

def test_quantile_buckets_three_equal_groups_and_missing():
    values = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, np.nan])
    labels = quantile_buckets(values)
    assert labels.iloc[-1] == "no data"
    counts = labels.iloc[:-1].str.split(" ").str[1].value_counts()
    assert counts.to_dict() == {"low": 2, "mid": 2, "high": 2}


def test_quantile_buckets_with_many_ties_gives_fewer_groups():
    # Like bounce-back rates: many values are exactly 1.0, so two edges merge.
    labels = quantile_buckets(pd.Series([0.1, 0.2, 0.3, 0.4, 0.5] + [1.0] * 7))
    assert set(labels.str.split(" ").str[1]) == {"low", "high"}
    # If all edges merge, there is one group, named "all".
    labels = quantile_buckets(pd.Series([0.0] * 5 + [1.0] * 5))
    assert set(labels.str.split(" ").str[1]) == {"all"}


def test_days_buckets():
    days = pd.Series([1, 2, 3, 4, 7, 8, 30, np.nan])
    assert days_buckets(days).tolist() == [
        "1 days", "2-3 days", "2-3 days", "4-7 days", "4-7 days", "8+ days", "8+ days", "no data",
    ]


def test_pick_reason():
    row = pd.Series({"avg_pts": 23.44, "last_pts": 9.0, "confidence": "strong"})
    assert pick_reason(row) == "avg 23.4, last game 9 pts, 2 bad games in a row"
    row["confidence"] = "normal"
    assert pick_reason(row) == "avg 23.4, last game 9 pts"


# --- full summary on synthetic data -----------------------------------------

@pytest.fixture(scope="module")
def picks():
    return make_picks(build_features(synthetic_games()))


@pytest.fixture(scope="module")
def summary(picks):
    return build_summary(picks)


def section(summary, rule, name, subset="brain"):
    rows = summary[(summary["line_rule"] == rule) & (summary["section"] == name)]
    return rows[rows["subset"] == subset]


def test_every_section_for_each_line_rule(summary):
    assert set(summary["line_rule"]) == {"fixed_gap", "history_70"}
    for rule in ("fixed_gap", "history_70"):
        assert set(summary.loc[summary["line_rule"] == rule, "section"]) == {
            "1_overview", "2_by_line", "3_bad_game_reason", "4_strength", "5_by_season",
        }


@pytest.mark.parametrize("rule", ["fixed_gap", "history_70"])
def test_sections_add_up(picks, summary, rule):
    rp = picks[picks["line_rule"] == rule]
    n_brain, n_all = int(rp["is_brain"].sum()), len(rp)
    assert n_brain > 0

    ov = summary[(summary["line_rule"] == rule) & (summary["section"] == "1_overview")].set_index(["group", "subset"])
    assert ov.loc[("all", "brain"), "picks"] == n_brain
    assert ov.loc[("normal", "brain"), "picks"] + ov.loc[("strong", "brain"), "picks"] == n_brain
    assert ov.loc[("all", "baseline"), "picks"] == n_all
    assert ov.loc[("non-bad games", "baseline"), "picks"] + n_brain == n_all

    for name in ("2_by_line", "5_by_season"):
        assert section(summary, rule, name)["picks"].sum() == n_brain
        assert section(summary, rule, name, "baseline")["picks"].sum() == n_all

    reasons = section(summary, rule, "3_bad_game_reason")
    for flag in ("low_minutes", "blowout", "unlucky_bad_game", "end_of_season", "last_game_end_of_season"):
        assert reasons[reasons["group"].str.startswith(flag + " ")]["picks"].sum() == n_brain

    strength = section(summary, rule, "4_strength")
    for factor in ("bb_rate_season", "bb_rate_all", "consistency", "drop_ratio", "days_since_last_game"):
        assert strength[strength["group"].str.startswith(factor + ":")]["picks"].sum() == n_brain


@pytest.fixture(scope="module")
def comparisons(picks):
    return build_comparisons(picks)


def test_format_report_has_all_sections(picks, summary, comparisons):
    text = format_report(summary, comparisons, picks)
    for title in ("1. Brain vs baseline", "2. By line", "3. By bad-game reason",
                  "4. By strength factor", "5. By season", "6. Factor vs baseline",
                  "7. By season average group", "8. Example picks"):
        assert text.count(title) == 2  # once per line rule
    assert "nan" not in text.lower()


def test_example_picks_are_the_same_every_run(picks, summary, comparisons):
    first = format_report(summary, comparisons, picks)
    assert first == format_report(build_summary(picks), build_comparisons(picks), picks)


# --- command line -----------------------------------------------------------

def test_run_main_saves_report(tmp_path, capsys):
    games_path = tmp_path / "games.parquet"
    synthetic_games().to_parquet(games_path, index=False)
    out_dir = tmp_path / "out"
    run.main(["--games", str(games_path), "--out-dir", str(out_dir)])
    assert "LINE RULE: fixed_gap" in (out_dir / config.REPORT_FILE).read_text()
    assert "Saved:" in capsys.readouterr().out


def test_run_main_without_games_file(tmp_path):
    with pytest.raises(SystemExit, match="download_games"):
        run.main(["--games", str(tmp_path / "missing.parquet")])


# --- max price display ------------------------------------------------------

def test_max_price_zero_or_below_shows_dash(picks, summary, comparisons):
    from src.backtest.report import _format_table
    rows = summary.head(2).copy()
    rows["max_price_cents"] = [-2.0, 0.0]
    table = _format_table(rows)
    assert "-2.0c" not in table and "0.0c" not in table


# --- groups for the comparison views ----------------------------------------

def test_open_outer_groups_cover_values_outside_brain_range():
    from src.backtest.groups import apply_buckets, bucket_edges
    edges = bucket_edges(pd.Series([0.5, 0.6, 0.7, 0.8, 0.9, 1.0]))
    labels = apply_buckets(pd.Series([0.0, 0.75, 5.0]), edges)
    names = labels.str.split(" ").str[1].tolist()
    assert names == ["low", "mid", "high"]  # 0.0 and 5.0 still get a group


def test_avg_buckets_boundaries():
    avg = pd.Series([14.0, 19.99, 20.0, 24.99, 25.0, 29.99, 13.9])
    assert avg_buckets(avg).tolist() == [
        "avg 14-19.9", "avg 14-19.9", "avg 20-24.9", "avg 20-24.9",
        "avg 25-29.9", "avg 25-29.9", "other",
    ]


# --- comparison views on a hand-made pick table -----------------------------

def hand_picks() -> pd.DataFrame:
    """Small pick table, one line rule, where every number can be checked by hand.

    Line 10: brain 2 picks (1 win), baseline 4 picks (3 wins).
    Line 20: brain 1 pick (1 win), baseline 2 picks (1 win).
    """
    rows = [
        # line, is_brain, hit, unlucky, end_of_season, avg
        (10, True, True, True, False, 15.0),
        (10, True, False, False, False, 15.0),
        (10, False, True, False, False, 15.0),
        (10, False, True, False, True, 15.0),
        (20, True, True, True, True, 26.0),
        (20, False, False, False, True, 26.0),
    ]
    df = pd.DataFrame(rows, columns=["line", "is_brain", "hit", "unlucky_bad_game", "end_of_season", "avg_pts"])
    df["line_rule"] = "fixed_gap"
    df["last_game_end_of_season"] = False
    df["low_minutes"] = False
    for col in ("consistency", "bb_rate_season", "bb_rate_all", "drop_ratio", "days_since_last_game"):
        df[col] = 1.0
    return df


def comparison(picks_df, factor, group, line):
    c = build_comparisons(picks_df)
    row = c[(c["factor"] == factor) & (c["group"] == group) & (c["line"] == line)]
    assert len(row) == 1
    return row.iloc[0]


def test_same_group_baseline():
    # end_of_season = yes: line 10 brain has none; line 20 brain 1/1, baseline 1/2 in the same group.
    row = comparison(hand_picks(), "end_of_season", "yes", "20+")
    assert (row["brain_picks"], row["brain_hit"]) == (1, 1.0)
    assert (row["base_picks"], row["base_hit"]) == (2, 0.5)
    assert row["diff_pts"] == pytest.approx(50.0)


def test_bad_game_only_factor_uses_overall_baseline():
    # unlucky = yes: brain line 10 has 1 pick; baseline = ALL line-10 rows (4, 3 wins).
    row = comparison(hand_picks(), "unlucky_bad_game", "yes", "10+")
    assert row["baseline"] == "overall"
    assert (row["base_picks"], row["base_hit"]) == (4, 0.75)


def test_all_lines_row_uses_brain_line_mix():
    # unlucky = yes: brain 1 pick on 10+ (base 75%) and 1 pick on 20+ (base 50%).
    # Expected baseline with the same line mix = (75% + 50%) / 2 = 62.5%.
    row = comparison(hand_picks(), "unlucky_bad_game", "yes", "all lines")
    assert row["brain_picks"] == 2 and row["brain_hit"] == 1.0
    assert row["base_hit"] == pytest.approx(0.625)
    assert row["diff_pts"] == pytest.approx(37.5)


def test_avg_group_view():
    row = comparison(hand_picks(), "season average", "avg 14-19.9", "10+")
    assert (row["brain_picks"], row["base_picks"]) == (2, 4)


@pytest.mark.parametrize("rule", ["fixed_gap", "history_70"])
def test_comparison_brain_counts_add_up(picks, comparisons, rule):
    n_brain = int(picks.loc[(picks["line_rule"] == rule) & picks["is_brain"]].shape[0])
    c = comparisons[(comparisons["line_rule"] == rule) & (comparisons["line"] == "all lines")]
    for factor, fc in c.groupby("factor"):
        assert fc["brain_picks"].sum() == n_brain, factor
