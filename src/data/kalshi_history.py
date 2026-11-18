"""Download Kalshi prices at tip-off - 60 minutes for our picks (PRD step 1.7).

Usage:
    python -m src.data.kalshi_history
    python -m src.data.kalshi_history --max-markets 50   # quick test run

Steps:
1. Read the series fee settings (fee_type, fee_multiplier) from the API.
2. Download all KXNBAPTS markets (historical + live).
3. Match each event to an NBA regular-season game (ET date + team codes) and
   each Kalshi name to an NBA player ID.
4. For markets that match a pick (game, player, line), read the 1-minute
   candlesticks and save the bid / ask / last price at tip-off - 60 minutes.

Results are cached in data/kalshi_prices.parquet: a re-run only downloads
markets that are not in the file yet.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import scheduleleaguev2

from src import config
from src.backtest.save import write_parquet
from src.brain.features import build_features
from src.brain.picks import make_picks
from src.data.download_games import fetch_season_log
from src.data.kalshi_api import KalshiClient
from src.data.kalshi_match import match_players, parse_markets, schedule_keys, snapshot

log = logging.getLogger(__name__)

SETTLED = {"finalized", "settled"}
CHECKPOINT_EVERY = 100  # save progress after this many downloaded markets


def call_schedule(season: str, mode: str = "") -> pd.DataFrame:
    """Raw NBA schedule with UTC tip-off times (one nba_api call)."""
    return scheduleleaguev2.ScheduleLeagueV2(
        season=season, timeout=config.REQUEST_TIMEOUT_SECONDS
    ).get_data_frames()[0]


def fetch_schedule(seasons, call=call_schedule) -> pd.DataFrame:
    """Regular-season games with tip-off time and team codes."""
    frames = []
    for season in seasons:
        raw = fetch_season_log(season, "schedule", call=call)
        raw = raw[raw["gameId"].astype(str).str.startswith("002")]  # 002 = regular season
        frames.append(pd.DataFrame({
            "game_id": raw["gameId"].astype(str),
            "tip_time": pd.to_datetime(raw["gameDateTimeUTC"], utc=True),
            "away": raw["awayTeam_teamTricode"],
            "home": raw["homeTeam_teamTricode"],
        }))
    return schedule_keys(pd.concat(frames, ignore_index=True))


def fee_settings(client: KalshiClient) -> float:
    """Fee multiplier of the series. Stops if the fee type is not the known one."""
    series = client.series(config.KALSHI_SERIES)
    if series.get("fee_type") != "quadratic":
        raise RuntimeError(f"Unknown Kalshi fee_type {series.get('fee_type')!r}: check the fee formula")
    return float(series["fee_multiplier"])


def pick_keys(games: pd.DataFrame) -> pd.DataFrame:
    """(game_id, player_id, line) of every pick (baseline incl. brain, both line rules)."""
    picks = make_picks(build_features(games))
    return picks[["game_id", "player_id", "line"]].drop_duplicates()


def matched_markets(markets: pd.DataFrame, schedule: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Markets on our lines, matched to a game and a player. Logs what did not match."""
    on_lines = markets[markets["line"].notna() & markets["status"].isin(SETTLED)]
    with_game = on_lines.merge(schedule[["event_key", "game_id", "tip_time"]], on="event_key", how="inner")
    with_game["player_id"] = match_players(with_game, games)
    no_player = with_game[with_game["player_id"].isna()]
    log.info("markets: %d total, %d settled on our lines, %d in a %s regular-season game, %d player matched",
             len(markets), len(on_lines), len(with_game), "/".join(config.KALSHI_SEASONS),
             with_game["player_id"].notna().sum())
    if len(no_player):
        top = no_player.drop_duplicates(["game_id", "kalshi_name"])["kalshi_name"].value_counts().head(15)
        log.info("player-games not matched (often: player did not play): %d. Most common: %s",
                 no_player["game_id"].astype(str).str.cat(no_player["kalshi_name"]).nunique(), top.to_dict())
    out = with_game[with_game["player_id"].notna()].copy()
    out["player_id"] = out["player_id"].astype("int64")
    out["line"] = out["line"].astype("int64")
    return out


def price_row(client: KalshiClient, market: pd.Series, fee_multiplier: float) -> dict:
    """Download candles for one market and read the snapshot at tip-off - 60 min."""
    at = market["tip_time"] - pd.Timedelta(minutes=config.PRICE_SNAPSHOT_MINUTES_BEFORE)
    candles = []
    if market["open_time"] < at:  # market opened before the snapshot time
        candles = client.candles(config.KALSHI_SERIES, market["ticker"], market["source"],
                                 int(market["open_time"].timestamp()) - 60, int(at.timestamp()))
    return {
        "ticker": market["ticker"], "game_id": market["game_id"], "player_id": market["player_id"],
        "kalshi_name": market["kalshi_name"], "line": market["line"], "tip_time": market["tip_time"],
        "snapshot_time": at, "result": market["result"], "fee_multiplier": fee_multiplier,
        **snapshot(candles, at),
    }


def load_cache(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def download_prices(client: KalshiClient, targets: pd.DataFrame, fee_multiplier: float,
                    path: Path, max_markets: int | None = None) -> pd.DataFrame:
    """Download snapshots for targets not in the cache yet. Saves progress as it goes."""
    cache = load_cache(path)
    done = set(cache["ticker"]) if len(cache) else set()
    todo = targets[~targets["ticker"].isin(done)]
    if max_markets is not None:
        todo = todo.head(max_markets)
    log.info("prices: %d in cache, %d to download", len(done), len(todo))
    rows = []
    for i, (_, market) in enumerate(todo.iterrows(), start=1):
        rows.append(price_row(client, market, fee_multiplier))
        if i % CHECKPOINT_EVERY == 0 or i == len(todo):
            cache = pd.concat([cache, pd.DataFrame(rows)], ignore_index=True)
            write_parquet(cache, path)
            rows = []
            log.info("  %d / %d downloaded", i, len(todo))
    return cache


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download Kalshi prices for the backtest picks.")
    parser.add_argument("--games", type=Path, default=config.GAMES_PATH)
    parser.add_argument("--out", type=Path, default=config.KALSHI_PRICES_PATH)
    parser.add_argument("--max-markets", type=int, default=None, help="Only download this many (for testing)")
    return parser.parse_args(argv)


def main(argv=None, client: KalshiClient | None = None, schedule_call=call_schedule) -> pd.DataFrame:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)
    if not args.games.exists():
        raise SystemExit(f"{args.games} not found. Run: python -m src.data.download_games")
    client = client or KalshiClient()
    games = pd.read_parquet(args.games)
    season_games = games[games["season"].isin(config.KALSHI_SEASONS)]

    fee_multiplier = fee_settings(client)
    markets = parse_markets(client.markets(config.KALSHI_SERIES))
    schedule = fetch_schedule(config.KALSHI_SEASONS, call=schedule_call)
    matched = matched_markets(markets, schedule, season_games)
    targets = matched.merge(pick_keys(games), on=["game_id", "player_id", "line"], how="inner")
    log.info("markets that match a pick: %d", len(targets))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    prices = download_prices(client, targets, fee_multiplier, args.out, args.max_markets)
    log.info("saved %d price rows to %s", len(prices), args.out)
    return prices


if __name__ == "__main__":
    main()
