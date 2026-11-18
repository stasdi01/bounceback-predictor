"""Small, vectorised brain rules shared by features (1.2) and picks (1.3).

All thresholds come from src/config.py.
"""

import pandas as pd

from src import config


def eligible_by_stats(avg_pts: pd.Series, games_before: pd.Series) -> pd.Series:
    """PRD 4.1 rules 1-2: 10+ earlier games and season average in [14, 30).

    The injury-report check (rule 3) is live-only and lives elsewhere.
    Missing averages (first game of a season) are never eligible.
    """
    return (
        (games_before >= config.MIN_GAMES_PLAYED)
        & (avg_pts >= config.MIN_SEASON_AVG)
        & (avg_pts < config.MAX_SEASON_AVG)
    ).fillna(False).astype(bool)


def is_bad_game(points: pd.Series, avg_pts: pd.Series) -> pd.Series:
    """PRD 4.2: a game is bad if points <= BAD_GAME_RATIO * season average.

    `avg_pts` is the average right before the game we predict. Missing values
    give False.
    """
    return (points <= config.BAD_GAME_RATIO * avg_pts).fillna(False).astype(bool)


def line_fixed_gap(avg_pts: pd.Series) -> pd.Series:
    """PRD 4.4 Rule A: highest line that is at least FIXED_GAP below the average.

    Returns NaN where no line fits (no pick).
    """
    line = pd.Series(float("nan"), index=avg_pts.index)
    for value in sorted(config.LINES):  # ascending: the last match is the highest
        line[avg_pts - config.FIXED_GAP >= value] = value
    return line


def line_history(features: pd.DataFrame) -> pd.Series:
    """PRD 4.4 Rule B: highest line reached in >= HISTORY_HIT_RATE of earlier games.

    Uses the hit_{line} columns from features. Returns NaN where no line fits.
    """
    line = pd.Series(float("nan"), index=features.index)
    for value in sorted(config.LINES):
        line[features[f"hit_{value}"] >= config.HISTORY_HIT_RATE] = value
    return line


def confidence(prev2_pts: pd.Series, avg_pts: pd.Series) -> pd.Series:
    """PRD 4.3, for rows where the last game was bad.

    "strong" if the game before last was also bad (vs today's average), else "normal".
    """
    two_bad = is_bad_game(prev2_pts, avg_pts)
    return two_bad.map({True: "strong", False: "normal"})
