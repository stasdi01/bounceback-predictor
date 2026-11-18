"""Tests for the Kalshi download: kalshi_api, kalshi_match, kalshi_history. No internet."""

import numpy as np
import pandas as pd
import pytest
import requests

from src import config
from src.data import kalshi_history as kh
from src.data.kalshi_api import HISTORICAL, LIVE, KalshiClient
from src.data.kalshi_match import (
    line_from_strike, match_players, normalize_name, parse_markets, player_from_title, schedule_keys, snapshot,
)
from tests.helpers import make_games


# --- names, titles, lines ---------------------------------------------------

@pytest.mark.parametrize("raw, clean", [
    ("Nikola Vučević", "nikola vucevic"),
    ("Jaren Jackson Jr.", "jaren jackson"),
    ("De'Aaron Fox", "de aaron fox"),
    ("P.J. Washington", "p j washington"),
    ("Shai Gilgeous-Alexander", "shai gilgeous alexander"),
    ("Gary Trent Jr", "gary trent"),
])
def test_normalize_name(raw, clean):
    assert normalize_name(raw) == clean


def test_player_from_both_title_formats():
    assert player_from_title("Cam Thomas: 25+ points") == "Cam Thomas"
    assert player_from_title("Dyson Daniels records 20+ points") == "Dyson Daniels"


def test_line_from_strike():
    assert line_from_strike(24.5) == 25
    assert line_from_strike(9.5) == 10
    assert np.isnan(line_from_strike(22.5))  # 23+ is not one of our lines


def test_schedule_key_uses_eastern_date():
    sched = pd.DataFrame({"tip_time": pd.to_datetime(["2026-03-05T00:30:00Z"]), "away": ["ATL"], "home": ["MIL"]})
    # 00:30 UTC on Mar 5 is 7:30 pm ET on Mar 4.
    assert schedule_keys(sched)["event_key"].iloc[0] == "26MAR04ATLMIL"


def test_match_players_handles_accents_and_ambiguous_names():
    games = pd.DataFrame({
        "game_id": ["g1", "g1", "g1", "g1"],
        "player_id": [1, 2, 3, 4],
        "player_name": ["Nikola Vučević", "Jaren Jackson Jr.", "Same Name", "Same Name"],
    })
    markets = pd.DataFrame({
        "game_id": ["g1", "g1", "g1", "g1", "g2"],
        "kalshi_name": ["Nikola Vucevic", "Jaren Jackson Jr.", "Same Name", "Not Playing", "Nikola Vucevic"],
    })
    out = match_players(markets, games)
    assert out.iloc[0] == 1 and out.iloc[1] == 2
    assert out.iloc[2:].isna().all()  # ambiguous, unknown, wrong game


# --- snapshot from candles --------------------------------------------------

def candle(ts, bid, ask, trade=None, volume="0.00"):
    return {"end_period_ts": ts, "yes_bid": {"close": f"{bid:.4f}"}, "yes_ask": {"close": f"{ask:.4f}"},
            "price": {"close": None if trade is None else f"{trade:.4f}"}, "volume": volume}


def test_snapshot_takes_last_candle_at_or_before_time():
    at = pd.Timestamp(1000, unit="s", tz="UTC")
    candles = [candle(900, 0.50, 0.55, trade=0.52, volume="10"), candle(1000, 0.60, 0.64),
               candle(1060, 0.10, 0.12, trade=0.11, volume="99")]  # after the snapshot: ignored
    snap = snapshot(candles, at)
    assert (snap["yes_bid"], snap["yes_ask"]) == (0.60, 0.64)
    assert snap["last_price"] == 0.52  # last trade before the snapshot
    assert snap["volume_before"] == 10.0


def test_snapshot_without_candles_is_empty():
    snap = snapshot([candle(2000, 0.5, 0.6)], pd.Timestamp(1000, unit="s", tz="UTC"))
    assert np.isnan(snap["yes_ask"]) and np.isnan(snap["yes_bid"])


# --- API client -------------------------------------------------------------

class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.text = str(payload)

    def json(self):
        return self._payload


def test_client_retries_on_429_then_succeeds():
    replies = [FakeResponse(429), FakeResponse(200, {"ok": 1})]
    waits = []
    client = KalshiClient(get=lambda url, params, timeout: replies.pop(0), sleep=waits.append)
    assert client.get_json("/x") == {"ok": 1}
    assert len(waits) == 2  # one back-off wait, one normal delay


def test_client_gives_up_and_raises_on_other_errors():
    client = KalshiClient(get=lambda url, params, timeout: FakeResponse(404), sleep=lambda s: None)
    with pytest.raises(RuntimeError, match="404"):
        client.get_json("/x")

    def timeout(url, params, timeout):
        raise requests.exceptions.ReadTimeout("slow")
    client = KalshiClient(get=timeout, sleep=lambda s: None)
    with pytest.raises(RuntimeError, match="tries failed"):
        client.get_json("/x")


def test_client_follows_cursor_and_merges_historical_and_live():
    pages = {
        ("/historical/markets", None): {"markets": [{"ticker": "A"}], "cursor": "c2"},
        ("/historical/markets", "c2"): {"markets": [{"ticker": "B"}], "cursor": ""},
        ("/markets", None): {"markets": [{"ticker": "B"}, {"ticker": "C"}], "cursor": ""},
    }

    def get(url, params, timeout):
        path = url.replace(config.KALSHI_API_BASE, "")
        return FakeResponse(200, pages[(path, params.get("cursor"))])

    out = KalshiClient(get=get, sleep=lambda s: None).markets("KXNBAPTS")
    assert [(m["ticker"], m["source"]) for m in out] == [("A", HISTORICAL), ("B", HISTORICAL), ("C", LIVE)]


# --- full download command, offline -----------------------------------------

def season_games() -> pd.DataFrame:
    """One player, 2025-26, 15 games vs BBB; game 13 follows a bad game (brain pick)."""
    games = make_games([24, 25] * 6 + [9, 22, 25], season="2025-26", start="2025-11-20")
    games["game_id"] = [f"00225{i:05d}" for i in range(len(games))]
    games["player_name"] = "Nikola Vučević"
    return games


def fake_schedule(games):
    def call(season, mode):
        tips = games["game_date"] + pd.Timedelta(hours=24, minutes=30)  # 7:30 pm ET same day
        return pd.DataFrame({
            "gameId": games["game_id"], "gameDateTimeUTC": tips.dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "awayTeam_teamTricode": "AAA", "homeTeam_teamTricode": "BBB",
        })
    return call


class FakeKalshi:
    """Stands in for KalshiClient. One market per game on line 20."""
    def __init__(self, games, fee_type="quadratic"):
        self.fee_type = fee_type
        self.candle_calls = 0
        self.markets_list = []
        for i, d in enumerate(games["game_date"]):
            key = (d + pd.Timedelta(days=1)).tz_localize("UTC").tz_convert("US/Eastern").strftime("%y%b%d").upper()
            self.markets_list.append({
                "ticker": f"T{i}", "event_ticker": f"KXNBAPTS-{key}AAABBB", "source": HISTORICAL,
                "title": "Nikola Vucevic: 20+ points", "floor_strike": 19.5, "status": "finalized",
                "result": "yes", "open_time": (d - pd.Timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            })

    def series(self, series):
        return {"fee_type": self.fee_type, "fee_multiplier": 1}

    def markets(self, series):
        return self.markets_list

    def candles(self, series, ticker, source, start_ts, end_ts):
        self.candle_calls += 1
        return [candle(end_ts - 300, 0.70, 0.74, trade=0.73, volume="5")]


def test_download_command_offline_and_cache(tmp_path):
    games = season_games()
    games_path, out = tmp_path / "games.parquet", tmp_path / "prices.parquet"
    games.to_parquet(games_path, index=False)
    client = FakeKalshi(games)
    args = ["--games", str(games_path), "--out", str(out)]

    prices = kh.main(args, client=client, schedule_call=fake_schedule(games))
    # Games 11-15 are eligible picks (10+ earlier games); all have a 20+ market.
    assert len(prices) == 5
    assert (prices["yes_ask"] == 0.74).all() and (prices["player_id"] == 1).all()
    tip_minus_60 = prices["tip_time"] - pd.Timedelta(minutes=config.PRICE_SNAPSHOT_MINUTES_BEFORE)
    assert (prices["snapshot_time"] == tip_minus_60).all()

    # Second run: everything is cached, no new candle downloads.
    calls = client.candle_calls
    again = kh.main(args, client=client, schedule_call=fake_schedule(games))
    assert client.candle_calls == calls and len(again) == 5


def test_download_stops_on_unknown_fee_type(tmp_path):
    games = season_games()
    games_path = tmp_path / "games.parquet"
    games.to_parquet(games_path, index=False)
    with pytest.raises(RuntimeError, match="fee_type"):
        kh.main(["--games", str(games_path), "--out", str(tmp_path / "p.parquet")],
                client=FakeKalshi(games, fee_type="flat"), schedule_call=fake_schedule(games))


def test_parse_markets_keeps_needed_fields():
    m = [{"ticker": "T", "source": LIVE, "event_ticker": "KXNBAPTS-26MAR04ATLMIL", "title": "A B: 15+ points",
          "floor_strike": 14.5, "open_time": "2026-03-04T23:06:00.123Z", "status": "finalized", "result": "no"}]
    row = parse_markets(m).iloc[0]
    assert (row["event_key"], row["kalshi_name"], row["line"]) == ("26MAR04ATLMIL", "A B", 15.0)
