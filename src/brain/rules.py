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
