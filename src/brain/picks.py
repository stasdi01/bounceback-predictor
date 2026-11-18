"""Apply the brain rules to the features (PRD step 1.3).

Output: one row per eligible player-game per line rule.
- All rows together are the BASELINE (every eligible game).
- Rows with is_brain = True are the BRAIN picks (last game was bad).
Rows where the line rule finds no line are dropped (no pick).
"""

import pandas as pd

from src import config
from src.brain.rules import confidence, eligible_by_stats, is_bad_game, line_fixed_gap, line_history

LINE_RULES = {
    "fixed_gap": lambda f: line_fixed_gap(f["avg_pts"]),
    "history_70": line_history,
}

# Columns copied from the features to every pick row.
INFO_COLUMNS = [
    "season", "game_id", "game_date", "player_id", "player_name", "team_id",
    "team_abbreviation", "matchup", "pts", "games_before", "avg_pts", "avg_min",
    "last_pts", "last_min", "prev2_pts", "last_team_margin", "drop_ratio",
    "normal_volume", "days_since_last_game", "bb_count_season", "bb_count_all",
]


def add_end_of_season_flags(features: pd.DataFrame) -> pd.DataFrame:
    """Analysis only, NOT a rule: is the game / the last game near the season end?

    Season end = last game date in our data for that season. This looks at the
    schedule end, which is known in advance, so it is fine for analysis. Note: for
    a season still in progress, the "end" would just be the latest date we have.
    """
    df = features.copy()
    season_end = df.groupby("season")["game_date"].transform("max")
    cutoff = season_end - pd.Timedelta(days=config.END_OF_SEASON_DAYS)
    last_game_date = df["game_date"] - pd.to_timedelta(df["days_since_last_game"], unit="D")
    df["end_of_season"] = df["game_date"] > cutoff
    df["last_game_end_of_season"] = (last_game_date > cutoff).fillna(False).astype(bool)
    return df


def add_trigger_and_flags(features: pd.DataFrame) -> pd.DataFrame:
    """Eligible rows only, with trigger, confidence and analysis flags."""
    features = add_end_of_season_flags(features)
    df = features[eligible_by_stats(features["avg_pts"], features["games_before"])].copy()
    df["is_brain"] = is_bad_game(df["last_pts"], df["avg_pts"])
    df["confidence"] = confidence(df["prev2_pts"], df["avg_pts"]).where(df["is_brain"])
    df["low_minutes"] = df["last_min"] < config.LOW_MINUTES_RATIO * df["avg_min"]
    df["blowout"] = df["last_team_margin"].abs() >= config.BLOWOUT_MARGIN
    df["unlucky_bad_game"] = df["is_brain"] & df["normal_volume"]
    return df


def pick_value_for_line(df: pd.DataFrame, prefix: str) -> pd.Series:
    """Take column `{prefix}{line}` for each row's chosen line."""
    out = pd.Series(float("nan"), index=df.index)
    for line in config.LINES:
        rows = df["line"] == line
        out[rows] = df.loc[rows, f"{prefix}{line}"]
    return out


def picks_for_rule(df: pd.DataFrame, rule_name: str) -> pd.DataFrame:
    """Choose the line with one rule, drop rows with no line, add the outcome."""
    df = df.assign(line_rule=rule_name, line=LINE_RULES[rule_name](df))
    df = df[df["line"].notna()].copy()
    df["line"] = df["line"].astype("int64")
    df["consistency"] = pick_value_for_line(df, "hit_")
    df["bb_rate_season"] = pick_value_for_line(df, "bb_rate_season_")
    df["bb_rate_all"] = pick_value_for_line(df, "bb_rate_all_")
    # The game's own points are used ONLY here, to check the result (PRD 4.8).
    df["hit"] = df["pts"] >= df["line"]
    return df


PICK_COLUMNS = INFO_COLUMNS + [
    "line_rule", "line", "is_brain", "confidence", "hit", "low_minutes", "blowout",
    "unlucky_bad_game", "end_of_season", "last_game_end_of_season",
    "consistency", "bb_rate_season", "bb_rate_all",
]


def make_picks(features: pd.DataFrame) -> pd.DataFrame:
    """Baseline and brain picks for every line rule, in one table."""
    eligible = add_trigger_and_flags(features)
    picks = pd.concat([picks_for_rule(eligible, name) for name in LINE_RULES], ignore_index=True)
    return picks[PICK_COLUMNS].sort_values(["line_rule", "game_date", "game_id", "player_id"]).reset_index(drop=True)
