"""All settings for the brain, backtest and live parts (PRD section 4.9).

Never hard-code these numbers in logic. Import them from here.
"""

from pathlib import Path

# Kalshi player-points lines (points >= line wins). 10 is the minimum line.
LINES: tuple[int, ...] = (10, 15, 20, 25, 30, 35)

# Player pool (4.1): season average must be >= MIN and < MAX.
MIN_SEASON_AVG: float = 14.0  # inclusive
MAX_SEASON_AVG: float = 30.0  # exclusive
MIN_GAMES_PLAYED: int = 10

# Trigger (4.2): bad game = last game points <= ratio * season average.
BAD_GAME_RATIO: float = 0.60

# Line choice (4.4).
FIXED_GAP: float = 3.0  # Rule A: line at least this many points below the average
HISTORY_HIT_RATE: float = 0.70  # Rule B: line reached in at least this share of games

# Minimum odds (4.5): never pick below these decimal odds.
MIN_ODDS: float = 1.40

# Money tracking (section 5): stake per pick, % of the starting monthly budget.
STAKE_PERCENT: float = 10.0

# "Unlucky bad game" strength factor (4.7): normal minutes and shot attempts.
UNLUCKY_MIN_RATIO: float = 0.75
UNLUCKY_FGA_RATIO: float = 0.75

# Analysis-only flags (Phase 1.3).
LOW_MINUTES_RATIO: float = 0.75
BLOWOUT_MARGIN: int = 20

# Max price (4.6): max_price_cents = hit_rate * 100 - FEE_BUFFER_CENTS.
# Kept in cents; code converts to dollars when comparing with Kalshi prices.
FEE_BUFFER_CENTS: float = 2.0

# Kalshi price snapshot is taken this many minutes before tip-off.
PRICE_SNAPSHOT_MINUTES_BEFORE: int = 60

# NBA data download (Phase 1.1).
SEASONS: tuple[str, ...] = ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26")
REQUEST_DELAY_SECONDS: float = 2.0  # wait between nba_api calls
MAX_RETRIES: int = 3  # total tries per call before giving up
REQUEST_TIMEOUT_SECONDS: int = 60

# Analysis-only flag (1.3): game in the last N days of the regular season.
END_OF_SEASON_DAYS: int = 7

# Backtest report (1.4).
CI_Z: float = 1.96  # z-value for the 95% range of the hit rate (Wilson method)
MIN_RELIABLE_PICKS: int = 300  # fewer picks -> marked "small sample"
STRENGTH_BUCKETS: int = 3  # low / mid / high groups for each strength factor
DAYS_SINCE_BINS: tuple[int, ...] = (1, 2, 4, 8)  # groups: 1 / 2-3 / 4-7 / 8+
REPORT_EXAMPLE_PICKS: int = 10
REPORT_SEED: int = 42

# File paths (relative to the project root).
GAMES_PATH: Path = Path("data/games.parquet")
REPORT_PATH: Path = Path("data/report.txt")
