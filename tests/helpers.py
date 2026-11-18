"""Shared test helpers."""

import numpy as np
import pandas as pd


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
