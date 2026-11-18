"""Tests for src/backtest/stats.py, report.py and run.py."""

import math

import numpy as np
import pandas as pd
import pytest

from src import config
from src.backtest import run
from src.backtest.report import build_summary, days_buckets, format_report, pick_reason, quantile_buckets
from src.backtest.stats import max_price_cents, min_odds, summarize, wilson_range
from src.brain.features import build_features
from src.brain.picks import make_picks
from tests.helpers import make_games


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

def synthetic_games() -> pd.DataFrame:
    """Several players over two seasons with random scoring around 15-25 ppg."""
    rng = np.random.default_rng(7)
    frames = []
    for pid in range(1, 9):
        for season, start in [("2023-24", "2023-10-24"), ("2024-25", "2024-10-22")]:
            mean = 14 + 2 * pid
            pts = np.clip(rng.normal(mean, mean * 0.4, 60).round(), 0, None).astype(int)
            frames.append(make_games(
                list(pts), player_id=pid, season=season, start=start,
                minutes=list(rng.integers(15, 40, 60)), fga=list(rng.integers(5, 25, 60)),
                margin=list(rng.integers(-30, 30, 60)),
            ))
    return pd.concat(frames, ignore_index=True)


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


def test_format_report_has_all_sections(picks, summary):
    text = format_report(summary, picks)
    for title in ("1. Brain vs baseline", "2. By line", "3. By bad-game reason",
                  "4. By strength factor", "5. By season", "6. Example picks"):
        assert text.count(title) == 2  # once per line rule
    assert "nan" not in text.lower()


def test_example_picks_are_the_same_every_run(picks, summary):
    assert format_report(summary, picks) == format_report(build_summary(picks), picks)


# --- command line -----------------------------------------------------------

def test_run_main_saves_report(tmp_path, capsys):
    games_path = tmp_path / "games.parquet"
    synthetic_games().to_parquet(games_path, index=False)
    report_path = tmp_path / "out" / "report.txt"
    run.main(["--games", str(games_path), "--report", str(report_path)])
    assert report_path.exists()
    assert "LINE RULE: fixed_gap" in report_path.read_text()
    assert "Report saved" in capsys.readouterr().out


def test_run_main_without_games_file(tmp_path):
    with pytest.raises(SystemExit, match="download_games"):
        run.main(["--games", str(tmp_path / "missing.parquet")])
