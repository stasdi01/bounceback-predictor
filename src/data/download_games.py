"""Download NBA regular-season player game logs and save them (PRD step 1.1).

Usage:
    python -m src.data.download_games                       # all seasons in config
    python -m src.data.download_games --seasons 2024-25 2025-26

One LeagueGameLog call per season and mode (player / team). The team's
PLUS_MINUS is the final score margin, joined to every player row.
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from pathlib import Path
from typing import Callable

import pandas as pd
import requests
from nba_api.stats.endpoints import leaguegamelog

from src import config

log = logging.getLogger(__name__)

PLAYER_MODE = "P"
TEAM_MODE = "T"
SEASON_PATTERN = re.compile(r"^\d{4}-\d{2}$")

# Raw nba_api column -> our column name. Only these columns are kept.
KEEP_COLUMNS = {
    "GAME_ID": "game_id",
    "GAME_DATE": "game_date",
    "PLAYER_ID": "player_id",
    "PLAYER_NAME": "player_name",
    "TEAM_ID": "team_id",
    "TEAM_ABBREVIATION": "team_abbreviation",
    "MATCHUP": "matchup",
    "WL": "wl",
    "MIN": "minutes",
    "PTS": "pts",
    "FGA": "fga",
    "FGM": "fgm",
    "team_margin": "team_margin",
}
OUTPUT_COLUMNS = ["season"] + list(KEEP_COLUMNS.values())

# Errors worth trying again (timeouts and dropped connections).
RETRY_ERRORS = (requests.exceptions.Timeout, requests.exceptions.ConnectionError)


def call_league_game_log(season: str, mode: str) -> pd.DataFrame:
    """One real nba_api call for a regular season, player or team mode."""
    endpoint = leaguegamelog.LeagueGameLog(
        season=season,
        player_or_team_abbreviation=mode,
        season_type_all_star="Regular Season",
        timeout=config.REQUEST_TIMEOUT_SECONDS,
    )
    return endpoint.get_data_frames()[0]


def fetch_season_log(
    season: str,
    mode: str,
    call: Callable[[str, str], pd.DataFrame] = call_league_game_log,
    sleep: Callable[[float], None] = time.sleep,
) -> pd.DataFrame:
    """Call the API with retries. Waits REQUEST_DELAY_SECONDS after every try."""
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            df = call(season, mode)
        except RETRY_ERRORS as err:
            log.warning("%s %s: try %d/%d failed (%s)", season, mode, attempt, config.MAX_RETRIES, err)
            sleep(config.REQUEST_DELAY_SECONDS)
            continue
        sleep(config.REQUEST_DELAY_SECONDS)
        if df.empty:
            raise ValueError(f"No {mode} rows returned for season {season}")
        return df
    raise RuntimeError(f"{season} {mode}: all {config.MAX_RETRIES} tries failed")


def join_team_margin(players: pd.DataFrame, teams: pd.DataFrame) -> pd.DataFrame:
    """Add the team's final margin (team PLUS_MINUS) to each player row."""
    margins = teams[["GAME_ID", "TEAM_ID", "PLUS_MINUS"]].rename(columns={"PLUS_MINUS": "team_margin"})
    if margins.duplicated(["GAME_ID", "TEAM_ID"]).any():
        raise ValueError("Team log has duplicate GAME_ID + TEAM_ID rows")
    merged = players.merge(margins, on=["GAME_ID", "TEAM_ID"], how="left", validate="many_to_one")
    missing = merged["team_margin"].isna().sum()
    if missing:
        raise ValueError(f"{missing} player rows have no matching team row")
    return merged


def clean_columns(df: pd.DataFrame, season: str) -> pd.DataFrame:
    """Keep only the PRD columns, rename to snake_case and fix types."""
    out = df[list(KEEP_COLUMNS)].rename(columns=KEEP_COLUMNS)
    out.insert(0, "season", season)
    out["game_date"] = pd.to_datetime(out["game_date"])
    for col in ["player_id", "team_id", "minutes", "pts", "fga", "fgm", "team_margin"]:
        out[col] = out[col].astype("int64")
    if out.duplicated(["game_id", "player_id"]).any():
        raise ValueError(f"Duplicate player rows in season {season}")
    return out[OUTPUT_COLUMNS]


def download_season(season: str, **fetch_kwargs) -> pd.DataFrame:
    """Download, join and clean one season."""
    players = fetch_season_log(season, PLAYER_MODE, **fetch_kwargs)
    teams = fetch_season_log(season, TEAM_MODE, **fetch_kwargs)
    return clean_columns(join_team_margin(players, teams), season)


def merge_with_existing(new: pd.DataFrame, path: Path) -> pd.DataFrame:
    """Replace only the seasons in `new`; keep other seasons already saved."""
    if not path.exists():
        combined = new
    else:
        old = pd.read_parquet(path)
        kept = old[~old["season"].isin(new["season"].unique())]
        combined = pd.concat([kept, new], ignore_index=True)
    return combined.sort_values(["season", "game_date", "game_id", "player_id"]).reset_index(drop=True)


def save_games(df: pd.DataFrame, path: Path) -> None:
    """Write to a temp file first, so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def season_arg(value: str) -> str:
    """argparse type: season must look like 2024-25."""
    if not SEASON_PATTERN.match(value):
        raise argparse.ArgumentTypeError(f"Season must look like 2024-25, got {value!r}")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download NBA player game logs.")
    parser.add_argument(
        "--seasons", nargs="+", type=season_arg, default=list(config.SEASONS),
        help="Seasons to download, e.g. 2024-25 2025-26 (default: all in config)",
    )
    parser.add_argument("--out", type=Path, default=config.GAMES_PATH, help="Output Parquet file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)
    frames = []
    for season in args.seasons:
        df = download_season(season)
        log.info("%s: %d player rows, %d games", season, len(df), df["game_id"].nunique())
        frames.append(df)
    combined = merge_with_existing(pd.concat(frames, ignore_index=True), args.out)
    save_games(combined, args.out)
    log.info("Saved %d rows (%s) to %s", len(combined), ", ".join(sorted(combined["season"].unique())), args.out)


if __name__ == "__main__":
    main()
