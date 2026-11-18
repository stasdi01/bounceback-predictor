"""Tests for src/data/download_games.py. No internet: all API calls are faked."""

import pandas as pd
import pytest
import requests

from src import config
from src.data import download_games as dg


def raw_players() -> pd.DataFrame:
    """Two player rows from one game, shaped like the real player-mode response."""
    return pd.DataFrame({
        "SEASON_ID": ["22024", "22024"],
        "PLAYER_ID": [1, 2],
        "PLAYER_NAME": ["Player One", "Player Two"],
        "TEAM_ID": [100, 200],
        "TEAM_ABBREVIATION": ["AAA", "BBB"],
        "TEAM_NAME": ["Team A", "Team B"],
        "GAME_ID": ["0022400001", "0022400001"],
        "GAME_DATE": ["2024-10-22", "2024-10-22"],
        "MATCHUP": ["AAA vs. BBB", "BBB @ AAA"],
        "WL": ["W", "L"],
        "MIN": [34, 30],
        "FGM": [9, 5],
        "FGA": [18, 14],
        "PTS": [25, 12],
        "PLUS_MINUS": [8, -3],  # player's own +/-, must NOT be used as team margin
        "FANTASY_PTS": [40.1, 20.2],
    })


def raw_teams() -> pd.DataFrame:
    """Matching team rows: team A won by 12."""
    return pd.DataFrame({
        "GAME_ID": ["0022400001", "0022400001"],
        "TEAM_ID": [100, 200],
        "PLUS_MINUS": [12, -12],
    })


@pytest.fixture
def no_sleep():
    """Record waits instead of really sleeping."""
    waits = []
    return waits, waits.append


# --- join_team_margin -------------------------------------------------------

def test_join_adds_team_margin_not_player_plus_minus():
    merged = dg.join_team_margin(raw_players(), raw_teams())
    assert merged["team_margin"].tolist() == [12, -12]


def test_join_fails_when_team_row_missing():
    teams = raw_teams().iloc[:1]  # team B row missing
    with pytest.raises(ValueError, match="no matching team row"):
        dg.join_team_margin(raw_players(), teams)


def test_join_fails_on_duplicate_team_rows():
    teams = pd.concat([raw_teams(), raw_teams().iloc[:1]])
    with pytest.raises(ValueError, match="duplicate"):
        dg.join_team_margin(raw_players(), teams)


# --- clean_columns ----------------------------------------------------------

def test_clean_keeps_only_prd_columns_with_right_types():
    out = dg.clean_columns(dg.join_team_margin(raw_players(), raw_teams()), "2024-25")
    assert out.columns.tolist() == [
        "season", "game_id", "game_date", "player_id", "player_name", "team_id",
        "team_abbreviation", "matchup", "wl", "minutes", "pts", "fga", "fgm", "team_margin",
    ]
    assert (out["season"] == "2024-25").all()
    assert pd.api.types.is_datetime64_any_dtype(out["game_date"])
    assert out["pts"].dtype == "int64"
    assert out["game_id"].iloc[0] == "0022400001"  # leading zeros kept


def test_clean_fails_on_duplicate_player_rows():
    players = pd.concat([raw_players(), raw_players().iloc[:1]])
    merged = dg.join_team_margin(players, raw_teams())
    with pytest.raises(ValueError, match="Duplicate"):
        dg.clean_columns(merged, "2024-25")


# --- fetch_season_log (retry and wait) --------------------------------------

def test_fetch_retries_after_timeouts_then_succeeds(no_sleep):
    waits, sleep = no_sleep
    calls = []

    def flaky(season, mode):
        calls.append(1)
        if len(calls) < config.MAX_RETRIES:
            raise requests.exceptions.ReadTimeout("slow")
        return raw_players()

    df = dg.fetch_season_log("2024-25", dg.PLAYER_MODE, call=flaky, sleep=sleep)
    assert len(df) == 2
    assert len(calls) == config.MAX_RETRIES
    # Waits after every try, failed or not.
    assert waits == [config.REQUEST_DELAY_SECONDS] * config.MAX_RETRIES


def test_fetch_gives_up_after_max_retries(no_sleep):
    _, sleep = no_sleep

    def always_fails(season, mode):
        raise requests.exceptions.ConnectionError("down")

    with pytest.raises(RuntimeError, match="tries failed"):
        dg.fetch_season_log("2024-25", dg.PLAYER_MODE, call=always_fails, sleep=sleep)


def test_fetch_fails_on_empty_result(no_sleep):
    _, sleep = no_sleep
    with pytest.raises(ValueError, match="No P rows"):
        dg.fetch_season_log("2099-00", dg.PLAYER_MODE, call=lambda s, m: pd.DataFrame(), sleep=sleep)


def test_download_season_end_to_end_with_fake_api(no_sleep):
    _, sleep = no_sleep

    def fake_call(season, mode):
        return raw_players() if mode == dg.PLAYER_MODE else raw_teams()

    out = dg.download_season("2024-25", call=fake_call, sleep=sleep)
    assert len(out) == 2
    assert out["team_margin"].tolist() == [12, -12]


# --- merge and save ---------------------------------------------------------

def season_frame(season: str, pts: int) -> pd.DataFrame:
    out = dg.clean_columns(dg.join_team_margin(raw_players(), raw_teams()), season)
    out["pts"] = pts
    return out


def test_merge_replaces_only_downloaded_seasons(tmp_path):
    path = tmp_path / "games.parquet"
    old = pd.concat([season_frame("2023-24", 10), season_frame("2024-25", 10)])
    dg.save_games(old, path)

    merged = dg.merge_with_existing(season_frame("2024-25", 99), path)

    by_season = merged.groupby("season")["pts"].unique()
    assert by_season["2023-24"].tolist() == [10]  # kept
    assert by_season["2024-25"].tolist() == [99]  # replaced
    assert len(merged) == 4


def test_merge_without_existing_file(tmp_path):
    merged = dg.merge_with_existing(season_frame("2024-25", 5), tmp_path / "none.parquet")
    assert len(merged) == 2


def test_save_creates_folder_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "sub" / "games.parquet"
    dg.save_games(season_frame("2024-25", 5), path)
    assert path.exists()
    assert list(path.parent.iterdir()) == [path]


# --- command line -----------------------------------------------------------

def test_cli_defaults_to_all_config_seasons():
    assert dg.parse_args([]).seasons == list(config.SEASONS)


def test_cli_accepts_chosen_seasons():
    assert dg.parse_args(["--seasons", "2023-24", "2025-26"]).seasons == ["2023-24", "2025-26"]


def test_cli_rejects_bad_season_format():
    with pytest.raises(SystemExit):
        dg.parse_args(["--seasons", "2024"])
