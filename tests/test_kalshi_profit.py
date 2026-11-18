"""Tests for src/backtest/kalshi_profit.py (section 9 money math)."""

import numpy as np
import pandas as pd
import pytest

from src import config
from src.backtest import run
from src.backtest.kalshi_profit import (
    NO_MARKET, NO_QUOTE, PRICED, add_profit, attach_prices, kalshi_analysis, result_mismatches, taker_fee,
)
from tests.helpers import make_games

C = config.KALSHI_BACKTEST_CONTRACTS


# --- fee formula ------------------------------------------------------------

@pytest.mark.parametrize("price, contracts, mult, fee", [
    (0.75, 100, 1, 1.32),  # 0.07 x 100 x 0.75 x 0.25 = 1.3125 -> rounds UP to 1.32
    (0.50, 100, 1, 1.75),  # exactly 1.75, no rounding
    (0.50, 1, 1, 0.02),    # 0.0175 -> 0.02
    (0.99, 1, 1, 0.01),    # tiny fee still costs 1 cent
    (0.75, 100, 0, 0.00),  # multiplier 0 = no fee
    (0.75, 100, 2, 2.63),  # 2 x 1.3125 = 2.625 -> 2.63
])
def test_taker_fee(price, contracts, mult, fee):
    assert taker_fee(price, contracts, mult) == pytest.approx(fee)


def test_taker_fee_no_float_noise_rounding():
    # 0.07 x 100 x 0.5 x 0.5 = 1.75 exactly; float noise must not make it 1.76.
    assert taker_fee(0.5, 100, 1) == pytest.approx(1.75)


# --- statuses, profit, min odds ---------------------------------------------

def picks_table() -> pd.DataFrame:
    """Five 2025-26 picks (one line rule) with different price situations."""
    return pd.DataFrame({
        "line_rule": "fixed_gap", "season": "2025-26",
        "game_date": pd.to_datetime(["2025-12-01"] * 5),
        "game_id": ["g1", "g2", "g3", "g4", "g5"], "player_id": 1, "line": 20,
        "is_brain": [True, True, False, False, True],
        "confidence": ["normal", "strong", None, None, "normal"],
        "hit": [True, False, True, True, True],
        "avg_pts": 22.0, "unlucky_bad_game": [True, False, False, False, False], "low_minutes": False,
    })


def prices_table() -> pd.DataFrame:
    # g1 priced 0.75, g2 priced 0.70, g3 ask 0.99 (no seller), g4 no quote, g5 no market.
    return pd.DataFrame({
        "game_id": ["g1", "g2", "g3", "g4"], "player_id": 1, "line": 20,
        "yes_bid": [0.70, 0.66, 0.0, np.nan], "yes_ask": [0.75, 0.70, 0.99, np.nan],
        "last_price": np.nan, "result": ["yes", "no", "yes", "yes"], "fee_multiplier": 1.0,
    })


def test_price_status():
    df = attach_prices(picks_table(), prices_table()).set_index("game_id")
    assert df["price_status"].to_dict() == {"g1": PRICED, "g2": PRICED, "g3": NO_QUOTE, "g4": NO_QUOTE, "g5": NO_MARKET}


def test_profit_per_pick_includes_fee():
    df = add_profit(attach_prices(picks_table(), prices_table())).set_index("game_id")
    cost_g1 = C * 0.75 + 1.32
    assert df.loc["g1", "cost"] == pytest.approx(cost_g1)
    assert df.loc["g1", "profit_units"] == pytest.approx((C - cost_g1) / cost_g1)  # win
    assert df.loc["g2", "profit_units"] == -1.0  # loss = lose the whole stake
    assert df.loc[["g3", "g4", "g5"], "profit_units"].isna().all()  # skipped picks
    assert df.loc["g1", "mid"] == pytest.approx(0.725)


def test_min_odds_boundary():
    # odds = 1 / ask: 0.71 -> 1.408 (ok), 0.72 -> 1.389 (too low).
    prices = prices_table().assign(yes_ask=[0.71, 0.72, 0.99, np.nan])
    df = add_profit(attach_prices(picks_table(), prices)).set_index("game_id")
    assert df.loc["g1", "passes_min_odds"] and not df.loc["g2", "passes_min_odds"]
    assert not df.loc["g3", "passes_min_odds"]  # not priced -> never passes


def test_result_mismatch_check():
    df = add_profit(attach_prices(picks_table(), prices_table()))
    assert result_mismatches(df) == 0
    wrong = prices_table().assign(result=["no", "no", "yes", "yes"])  # g1 hit but Kalshi says no
    assert result_mismatches(add_profit(attach_prices(picks_table(), wrong))) == 1


def test_summary_counts_and_roi():
    res = kalshi_analysis(picks_table(), prices_table())
    s = res.summary
    brain = s[(s["odds_filter"] == "all priced") & (s["view"] == "overall") & (s["subset"] == "brain")].iloc[0]
    assert (brain["picks"], brain["wins"]) == (2, 1)  # g1 win, g2 loss (g5 no market)
    cost_g1 = C * 0.75 + 1.32
    assert brain["roi"] == pytest.approx(((C - cost_g1) / cost_g1 - 1) / 2)
    assert brain["avg_ask"] == pytest.approx(0.725)
    assert brain["small_sample"]
    cov = res.coverage.set_index("subset").drop(columns="line_rule")
    # ask 0.75 -> odds 1.33 (too low), ask 0.70 -> odds 1.43 (ok)
    assert cov.loc["brain"].to_dict() == {"picks_in_period": 3, "no_market": 1, "no_quote": 0,
                                         "priced": 2, "priced_odds_ok": 1}
    for view in ("confidence", "line", "season average", "unlucky_bad_game", "low_minutes"):
        assert view in set(s["view"])


def test_report_has_section_9_with_and_without_prices():
    games = make_games([24, 25] * 6 + [9, 22, 25], season="2025-26", start="2025-11-20")
    result = run.run_backtest(games)
    assert "No Kalshi prices" in result.report
    picks = result.picks
    prices = picks[["game_id", "player_id", "line"]].drop_duplicates().assign(
        yes_bid=0.70, yes_ask=0.74, last_price=0.73, result="yes", fee_multiplier=1.0)
    with_prices = run.run_backtest(games, prices)
    assert "9. Kalshi prices" in with_prices.report and "Coverage:" in with_prices.report
    assert "nan" not in with_prices.report.lower()
