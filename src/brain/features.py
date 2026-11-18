"""Build per player-game features from data/games.parquet (PRD step 1.2).

No-cheating rule (PRD 4.8): every feature for a game uses ONLY that player's
earlier games. The trick used everywhere below:

    sum of earlier games = running total (cumsum) - this game's own value

so the current game's stats never leak into its own features.
"""

import numpy as np
import pandas as pd

from src import config
from src.brain.rules import eligible_by_stats, is_bad_game

SEASON_KEYS = ["player_id", "season"]
OUTPUT_SORT = ["season", "game_date", "game_id", "player_id"]


def _sum_before(df: pd.DataFrame, values: pd.Series, keys: list[str]) -> pd.Series:
    """Sum of `values` over the player's earlier rows within `keys` groups."""
    return values.groupby([df[k] for k in keys]).cumsum() - values


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """numerator / denominator, with NaN (not inf) when denominator is 0."""
    return numerator / denominator.replace(0, np.nan)


def add_averages(df: pd.DataFrame) -> pd.DataFrame:
    """games_before and season averages from earlier games only."""
    df["games_before"] = df.groupby(SEASON_KEYS).cumcount()
    for col, name in [("pts", "avg_pts"), ("minutes", "avg_min"), ("fga", "avg_fga")]:
        df[name] = _safe_divide(_sum_before(df, df[col].astype(float), SEASON_KEYS), df["games_before"])
    return df


def add_last_games(df: pd.DataFrame) -> pd.DataFrame:
    """Stats from his last game and the game before that (this season)."""
    grouped = df.groupby(SEASON_KEYS)
    for col, name in [("pts", "last_pts"), ("minutes", "last_min"),
                      ("fga", "last_fga"), ("team_margin", "last_team_margin")]:
        df[name] = grouped[col].shift(1)
    df["prev2_pts"] = grouped["pts"].shift(2)
    df["days_since_last_game"] = grouped["game_date"].diff().dt.days
    return df


def add_line_hit_rates(df: pd.DataFrame) -> pd.DataFrame:
    """hit_{line}: share of earlier games this season where pts >= line."""
    for line in config.LINES:
        reached = (df["pts"] >= line).astype(float)
        df[f"hit_{line}"] = _safe_divide(_sum_before(df, reached, SEASON_KEYS), df["games_before"])
    return df


def add_strength_factors(df: pd.DataFrame) -> pd.DataFrame:
    """drop_ratio and normal_volume (PRD 4.7). Uses today's averages, like 4.2."""
    df["drop_ratio"] = _safe_divide(df["last_pts"], df["avg_pts"])
    normal_min = df["last_min"] >= config.UNLUCKY_MIN_RATIO * df["avg_min"]
    normal_fga = df["last_fga"] >= config.UNLUCKY_FGA_RATIO * df["avg_fga"]
    df["normal_volume"] = (normal_min & normal_fga).fillna(False).astype(bool)
    return df


def add_bounce_back_rates(df: pd.DataFrame) -> pd.DataFrame:
    """Personal bounce-back rate (PRD 4.7), season-only and all-history versions.

    A game G is a "bounce-back chance" if the brain would have triggered on it
    at that time. Its outcome (pts at G) is only counted for LATER games.
    """
    would_trigger = eligible_by_stats(df["avg_pts"], df["games_before"]) & is_bad_game(
        df["last_pts"], df["avg_pts"]
    )
    chances = would_trigger.astype(float)
    for scope, keys in [("season", SEASON_KEYS), ("all", ["player_id"])]:
        count = _sum_before(df, chances, keys)
        df[f"bb_count_{scope}"] = count.astype("int64")
        for line in config.LINES:
            success = (would_trigger & (df["pts"] >= line)).astype(float)
            df[f"bb_rate_{scope}_{line}"] = _safe_divide(_sum_before(df, success, keys), count)
    return df


def build_features(games: pd.DataFrame) -> pd.DataFrame:
    """Return `games` plus all step 1.2 feature columns, one row per player-game."""
    # Sort by player then date: every running total below runs in time order.
    # Season strings ("2021-22") sort in time order too, for the all-history version.
    df = games.sort_values(["player_id", "game_date", "game_id"]).reset_index(drop=True)
    for step in (add_averages, add_last_games, add_line_hit_rates,
                 add_strength_factors, add_bounce_back_rates):
        df = step(df)
    return df.sort_values(OUTPUT_SORT).reset_index(drop=True)
