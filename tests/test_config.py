"""Sanity checks for src/config.py, so a typo in a setting is caught early."""

from src import config


def test_lines_match_kalshi_thresholds():
    assert config.LINES == (10, 15, 20, 25, 30, 35)
    assert list(config.LINES) == sorted(config.LINES)
    assert min(config.LINES) == 10


def test_season_average_range_is_valid():
    assert 0 < config.MIN_SEASON_AVG < config.MAX_SEASON_AVG


def test_min_games_is_positive():
    assert config.MIN_GAMES_PLAYED > 0


def test_ratios_are_between_zero_and_one():
    ratios = [
        config.BAD_GAME_RATIO,
        config.HISTORY_HIT_RATE,
        config.UNLUCKY_MIN_RATIO,
        config.UNLUCKY_FGA_RATIO,
        config.LOW_MINUTES_RATIO,
    ]
    for ratio in ratios:
        assert 0 < ratio < 1


def test_money_settings_are_valid():
    assert config.MIN_ODDS > 1  # odds of 1.0 or less can never win money
    assert 0 < config.STAKE_PERCENT <= 100
    assert 0 <= config.FEE_BUFFER_CENTS < 100


def test_other_positive_settings():
    assert config.FIXED_GAP > 0
    assert config.BLOWOUT_MARGIN > 0
    assert config.PRICE_SNAPSHOT_MINUTES_BEFORE > 0


def test_download_settings_are_valid():
    assert len(config.SEASONS) > 0
    assert list(config.SEASONS) == sorted(config.SEASONS)
    assert config.REQUEST_DELAY_SECONDS >= 0
    assert config.MAX_RETRIES >= 1
    assert config.REQUEST_TIMEOUT_SECONDS > 0
