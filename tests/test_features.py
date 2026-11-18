"""Tests for src/brain/features.py and src/brain/rules.py."""

import numpy as np
import pandas as pd
import pytest

from src import config
from src.brain.features import build_features
from src.brain.rules import eligible_by_stats, is_bad_game


def make_games(pts, player_id=1, season="2024-25", start="2024-10-22",
               minutes=None, fga=None, margin=None, gap_days=2) -> pd.DataFrame:
    """One player's games with the columns of data/games.parquet."""
    n = len(pts)
    dates = pd.to_datetime(start) + pd.to_timedelta(np.arange(n) * gap_days, unit="D")
    return pd.DataFrame({
        "season": season,
        "game_id": [f"{season[:4]}{player_id:03d}{i:04d}" for i in range(n)],
        "game_date": dates,
        "player_id": player_id,
        "player_name": f"Player {player_id}",
        "team_id": 100,
        "team_abbreviation": "AAA",
        "matchup": "AAA vs. BBB",
        "wl": "W",
        "minutes": minutes if minutes is not None else [30] * n,
        "pts": pts,
        "fga": fga if fga is not None else [15] * n,
        "fgm": [5] * n,
        "team_margin": margin if margin is not None else [5] * n,
    })


def random_games(seed=0) -> pd.DataFrame:
    """Two players over two seasons with random stats."""
    rng = np.random.default_rng(seed)
    frames = []
    for pid in (1, 2):
        for season, start in [("2023-24", "2023-10-24"), ("2024-25", "2024-10-22")]:
            n = 40
            frames.append(make_games(
                list(rng.integers(0, 40, n)), player_id=pid, season=season, start=start,
                minutes=list(rng.integers(10, 40, n)), fga=list(rng.integers(3, 25, n)),
                margin=list(rng.integers(-30, 30, n)),
            ))
    return pd.concat(frames, ignore_index=True)


INPUT_COLUMNS = list(make_games([1]).columns)


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in INPUT_COLUMNS]


# --- rules ------------------------------------------------------------------

def test_eligible_by_stats_boundaries():
    avg = pd.Series([14.0, 13.99, 29.99, 30.0, 20.0, np.nan])
    games = pd.Series([10, 10, 10, 10, 9, 20])
    assert eligible_by_stats(avg, games).tolist() == [True, False, True, False, False, False]


def test_bad_game_is_inclusive_at_60_percent():
    avg = pd.Series([20.0, 20.0, np.nan])
    pts = pd.Series([12, 13, 5])
    assert is_bad_game(pts, avg).tolist() == [True, False, False]


# --- basic features, checked by hand ----------------------------------------

def test_hand_example():
    out = build_features(make_games([10, 20, 30], minutes=[30, 20, 40], fga=[10, 20, 30]))
    assert out["games_before"].tolist() == [0, 1, 2]
    assert out["avg_pts"].tolist()[1:] == [10.0, 15.0]
    assert np.isnan(out["avg_pts"].iloc[0])
    assert out["avg_min"].tolist()[1:] == [30.0, 25.0]
    assert out["last_pts"].tolist()[1:] == [10.0, 20.0]
    assert out["last_min"].tolist()[1:] == [30.0, 20.0]
    assert out["prev2_pts"].tolist()[2] == 10.0
    assert out["hit_10"].tolist()[1:] == [1.0, 1.0]
    assert out["hit_15"].tolist()[1:] == [0.0, 0.5]
    assert out["hit_20"].tolist()[1:] == [0.0, 0.5]
    assert out["drop_ratio"].tolist()[2] == pytest.approx(20 / 15)
    assert out["days_since_last_game"].tolist()[1:] == [2.0, 2.0]


def test_normal_volume():
    # Each row looks back at the previous game vs today's average, and today's
    # average includes that previous game.
    out = build_features(make_games(
        [20] * 5,
        minutes=[30, 30, 15, 30, 30],  # row 3: 15 min vs avg 25 -> 60%, low
        fga=[16, 16, 16, 8, 16],       # row 4: 8 FGA vs avg 14 -> 57%, low
    ))
    # Row 0: no last game. Row 1: normal. Row 3: low minutes. Row 4: low FGA.
    assert out["normal_volume"].tolist() == [False, True, True, False, False]


def test_normal_volume_boundary_is_inclusive():
    # Last game exactly 75% of average (avg 40, last 30) -> still normal.
    out = build_features(make_games([20, 20, 20], minutes=[40, 30, 30], fga=[20, 15, 15]))
    assert out["normal_volume"].iloc[2] == True


def test_zero_average_gives_nan_drop_ratio_not_inf():
    out = build_features(make_games([0, 0, 5]))
    assert np.isnan(out["drop_ratio"].iloc[2])
    assert not np.isinf(out.select_dtypes("number")).any().any()


# --- no-cheating rule (PRD 4.8) ---------------------------------------------

def test_own_game_points_do_not_change_its_features():
    games = random_games()
    base = build_features(games)
    for row in [5, 30, 55, 100]:
        changed = games.copy()
        changed.loc[row, ["pts", "minutes", "fga", "team_margin"]] = [99, 48, 40, 50]
        out = build_features(changed)
        key = games.loc[row, ["game_id", "player_id"]]
        mask = (out["game_id"] == key["game_id"]) & (out["player_id"] == key["player_id"])
        cols = feature_columns(out)
        pd.testing.assert_frame_equal(
            out.loc[mask, cols].reset_index(drop=True),
            base.loc[mask, cols].reset_index(drop=True),
        )


def test_future_games_do_not_change_earlier_features():
    games = random_games()
    cutoff = pd.Timestamp("2024-01-15")
    changed = games.copy()
    future = changed["game_date"] > cutoff
    rng = np.random.default_rng(1)
    changed.loc[future, "pts"] = rng.integers(0, 60, future.sum())
    changed.loc[future, "minutes"] = rng.integers(0, 48, future.sum())

    base, out = build_features(games), build_features(changed)
    past = base["game_date"] <= cutoff
    assert past.sum() > 0
    cols = feature_columns(base)
    pd.testing.assert_frame_equal(out.loc[past, cols], base.loc[past, cols])


def test_avg_pts_excludes_own_game():
    out = build_features(make_games([10, 50]))
    assert out["avg_pts"].iloc[1] == 10.0


# --- seasons and ordering ---------------------------------------------------

def test_new_season_starts_from_zero():
    games = pd.concat([
        make_games([20] * 5, season="2023-24", start="2023-10-24"),
        make_games([30] * 3, season="2024-25", start="2024-10-22"),
    ])
    out = build_features(games)
    first_new = out[out["season"] == "2024-25"].iloc[0]
    assert first_new["games_before"] == 0
    assert np.isnan(first_new["avg_pts"])
    assert np.isnan(first_new["last_pts"])
    assert np.isnan(first_new["days_since_last_game"])


def test_shuffled_input_gives_same_result():
    games = random_games()
    base = build_features(games)
    out = build_features(games.sample(frac=1, random_state=3))
    pd.testing.assert_frame_equal(out, base)


def test_traded_player_average_includes_both_teams():
    games = make_games([10, 20, 30])
    games.loc[2, "team_id"] = 200  # traded before game 3
    out = build_features(games)
    assert out["avg_pts"].iloc[2] == 15.0


# --- personal bounce-back rate ----------------------------------------------

def bounce_back_games(season="2024-25", start="2024-10-22", player_id=1):
    """12 games of 20 pts, a 5-pt bad game, a 25-pt bounce-back, then one more."""
    return make_games([20] * 12 + [5, 25, 20], season=season, start=start, player_id=player_id)


def test_bounce_back_rate_counts_only_earlier_outcomes():
    out = build_features(bounce_back_games())
    chance = out.iloc[13]  # game after the bad game: the brain would trigger here
    assert chance["bb_count_season"] == 0  # its own outcome is not counted yet
    assert np.isnan(chance["bb_rate_season_20"])

    after = out.iloc[14]
    assert after["bb_count_season"] == 1
    assert after["bb_rate_season_20"] == 1.0
    assert after["bb_rate_season_25"] == 1.0
    assert after["bb_rate_season_30"] == 0.0


def test_bad_game_before_10_games_is_not_a_chance():
    # Bad game in game 5, bounce back in game 6: too few games, does not count.
    out = build_features(make_games([20, 20, 20, 20, 5, 25] + [20] * 10))
    assert (out["bb_count_season"] == 0).all()


def test_low_average_player_bad_game_is_not_a_chance():
    # Average ~13, below MIN_SEASON_AVG: his bad games never count.
    out = build_features(make_games([13] * 12 + [2, 20, 13]))
    assert out["avg_pts"].iloc[13] < config.MIN_SEASON_AVG
    assert (out["bb_count_season"] == 0).all()


def test_bounce_back_all_version_carries_over_seasons():
    games = pd.concat([
        bounce_back_games(season="2023-24", start="2023-10-24"),
        make_games([20] * 3, season="2024-25", start="2024-10-22"),
    ])
    out = build_features(games)
    new_season = out[out["season"] == "2024-25"]
    assert (new_season["bb_count_season"] == 0).all()
    assert (new_season["bb_count_all"] == 1).all()
    assert (new_season["bb_rate_all_25"] == 1.0).all()


def test_bounce_back_is_per_player():
    games = pd.concat([bounce_back_games(player_id=1), make_games([20] * 15, player_id=2)])
    out = build_features(games)
    assert (out.loc[out["player_id"] == 2, "bb_count_all"] == 0).all()
