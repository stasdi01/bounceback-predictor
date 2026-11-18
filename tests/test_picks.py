"""Tests for the step 1.3 rules: src/brain/rules.py line/confidence and src/brain/picks.py."""

import numpy as np
import pandas as pd
import pytest

from src.brain.features import build_features
from src.brain.picks import make_picks
from src.brain.rules import confidence, line_fixed_gap, line_history
from tests.helpers import make_games

LILLARD_START = [24, 25] * 6  # 12 games around 24-25 points


def picks_for(games: pd.DataFrame) -> pd.DataFrame:
    return make_picks(build_features(games))


def last_game_picks(games: pd.DataFrame) -> pd.DataFrame:
    """Pick rows (both line rules) for the player's final game."""
    picks = picks_for(games)
    return picks[picks["game_date"] == games["game_date"].max()].set_index("line_rule")


# --- line rules (PRD 4.4) ---------------------------------------------------

@pytest.mark.parametrize("avg, line", [(23, 20), (26, 20), (28, 25), (15, 10), (29.9, 25)])
def test_fixed_gap_prd_examples(avg, line):
    assert line_fixed_gap(pd.Series([float(avg)])).iloc[0] == line


def test_fixed_gap_no_line_fits():
    # 12.9 - 3 = 9.9 < 10: no pick. Exactly 13 - 3 = 10 still fits.
    out = line_fixed_gap(pd.Series([12.9, 13.0]))
    assert np.isnan(out.iloc[0])
    assert out.iloc[1] == 10


def hit_rates(**rates) -> pd.DataFrame:
    """One features row with hit_{line} columns (missing lines = 0)."""
    row = {f"hit_{line}": 0.0 for line in (10, 15, 20, 25, 30, 35)}
    row.update({f"hit_{k[1:]}": v for k, v in rates.items()})
    return pd.DataFrame([row])


def test_history_picks_highest_line_at_70_percent():
    assert line_history(hit_rates(_10=1.0, _15=0.9, _20=0.75, _25=0.5)).iloc[0] == 20


def test_history_exactly_70_percent_counts():
    assert line_history(hit_rates(_10=1.0, _15=0.7)).iloc[0] == 15


def test_history_no_line_fits():
    assert np.isnan(line_history(hit_rates(_10=0.69)).iloc[0])


def test_history_rule_depends_on_the_player():
    """PRD 1.6 test 6: both average 28; the steady one gets 25+, the other a lower line."""
    steady = make_games([24, 27, 30, 26, 29, 28, 31, 27, 25, 33, 30], player_id=1)
    swingy = make_games([15, 38, 22, 41, 19, 36, 20, 40, 17, 32, 30], player_id=2)
    picks = picks_for(pd.concat([steady, swingy]))
    hist = picks[(picks["line_rule"] == "history_70") & (picks["games_before"] == 10)].set_index("player_id")
    assert hist.loc[1, "avg_pts"] == hist.loc[2, "avg_pts"] == 28.0
    assert hist.loc[1, "line"] == 25
    assert hist.loc[2, "line"] == 20  # reached 20+ in exactly 7 of 10 games


# --- confidence (PRD 4.3) ---------------------------------------------------

def test_confidence():
    avg = pd.Series([20.0, 20.0, 20.0])
    prev2 = pd.Series([12, 13, np.nan])  # bad, not bad, missing
    assert confidence(prev2, avg).tolist() == ["strong", "normal", "normal"]


# --- acceptance tests (PRD 1.6) ---------------------------------------------

def test_lillard_example_normal_pick_on_20():
    rows = last_game_picks(make_games(LILLARD_START + [9, 22]))
    assert len(rows) == 2  # one per line rule
    for rule in ("fixed_gap", "history_70"):
        assert rows.loc[rule, "is_brain"]
        assert rows.loc[rule, "confidence"] == "normal"
        assert rows.loc[rule, "line"] == 20
        assert rows.loc[rule, "hit"]  # scored 22


def test_two_bad_games_in_a_row_is_strong():
    rows = last_game_picks(make_games(LILLARD_START + [9, 8, 22]))
    assert (rows["confidence"] == "strong").all()
    assert rows["is_brain"].all()


def test_high_scorer_is_skipped():
    picks = picks_for(make_games([39] * 12 + [10, 40]))
    assert picks.empty


def test_low_scorer_is_skipped():
    picks = picks_for(make_games([13, 14] * 6 + [5, 15]))
    assert picks.empty


def test_fewer_than_10_games_no_pick():
    picks = picks_for(make_games([24] * 8 + [5, 25]))
    assert picks.empty


# --- baseline, flags, outcome -----------------------------------------------

def test_baseline_includes_every_eligible_game_and_brain_is_subset():
    games = make_games(LILLARD_START + [9, 22, 25, 24])
    picks = picks_for(games)
    fixed = picks[picks["line_rule"] == "fixed_gap"]
    # 16 games: games 11-16 (games_before 10..15) are eligible -> 6 baseline rows.
    assert fixed["games_before"].tolist() == [10, 11, 12, 13, 14, 15]
    assert fixed["is_brain"].sum() == 1
    assert fixed["confidence"].isna().sum() == 5  # only brain rows have a confidence


def test_no_line_means_no_row_for_that_rule_only():
    # Avg 14: fixed_gap 14 - 3 = 11 -> 10+. history: reached 10+ in only 60% -> no line.
    games = make_games([20, 20, 20, 20, 20, 20, 7, 7, 7, 7, 14])
    picks = picks_for(games)
    assert picks["line_rule"].tolist() == ["fixed_gap"]


def test_analysis_flags():
    # Last game: 8 pts in 10 minutes in a 25-point loss.
    games = make_games(LILLARD_START + [8, 22], minutes=[34] * 12 + [10, 34],
                       margin=[5] * 12 + [-25, 5])
    row = last_game_picks(games).loc["fixed_gap"]
    assert row["low_minutes"] and row["blowout"]
    assert not row["unlucky_bad_game"]  # low minutes -> not "unlucky"


def test_unlucky_bad_game_and_flag_limits():
    # Normal minutes and shots, margin exactly 19 -> unlucky, not blowout.
    games = make_games(LILLARD_START + [8, 22], margin=[5] * 12 + [19, 5])
    row = last_game_picks(games).loc["fixed_gap"]
    assert row["unlucky_bad_game"]
    assert not row["low_minutes"] and not row["blowout"]
    # Exactly 20 is a blowout.
    games = make_games(LILLARD_START + [8, 22], margin=[5] * 12 + [-20, 5])
    assert last_game_picks(games).loc["fixed_gap", "blowout"]


def test_strength_values_use_the_chosen_line():
    rows = last_game_picks(make_games(LILLARD_START + [9, 22]))
    row = rows.loc["fixed_gap"]
    assert row["consistency"] == pytest.approx(12 / 13)  # 20+ in 12 of 13 earlier games
    assert row["drop_ratio"] == pytest.approx(9 / row["avg_pts"])


def test_own_points_change_only_the_hit():
    base = last_game_picks(make_games(LILLARD_START + [9, 22]))
    changed = last_game_picks(make_games(LILLARD_START + [9, 3]))
    assert base["hit"].all() and not changed["hit"].any()
    other = [c for c in base.columns if c not in ("pts", "hit")]
    pd.testing.assert_frame_equal(base[other], changed[other])


# --- end-of-season flags (analysis only) ------------------------------------

def test_end_of_season_flags():
    # 20 games, 2 days apart. Season end = game 20. Last 7 days = games 17-20
    # (0, 2, 4, 6 days before the end); game 16 is 8 days before.
    picks = picks_for(make_games([20] * 20))
    fixed = picks[picks["line_rule"] == "fixed_gap"].set_index("games_before")
    # games_before 15 = game 16, ... games_before 19 = game 20
    assert fixed["end_of_season"].to_dict() == {
        10: False, 11: False, 12: False, 13: False, 14: False,
        15: False, 16: True, 17: True, 18: True, 19: True,
    }
    # The last game (bad game) is in the last 7 days from game 18 on.
    assert fixed["last_game_end_of_season"].to_dict() == {
        10: False, 11: False, 12: False, 13: False, 14: False,
        15: False, 16: False, 17: True, 18: True, 19: True,
    }


def test_end_of_season_uses_each_seasons_own_end():
    games = pd.concat([
        make_games([20] * 15, season="2023-24", start="2023-10-24"),
        make_games([20] * 15, season="2024-25", start="2024-10-22"),
    ])
    picks = picks_for(games)
    last_rows = picks[picks["games_before"] == 14]
    assert len(last_rows) == 4  # 2 seasons x 2 line rules
    assert last_rows["end_of_season"].all()
