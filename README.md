# Bounceback Predictor

A rule-based model that predicts NBA player points on Kalshi lines
(10+, 15+, 20+, 25+, 30+, 35+). The idea: **a good scorer who had a bad
game will bounce back in the next game.** The project tests this idea
honestly on past seasons and with live paper trading (no real money).

Full rules and plan: [`docs/PRD.md`](docs/PRD.md).

## Status

Phase 0 (project setup) is done. Phase 1: step 1.1 (download data),
step 1.2 (build features, `src/brain/features.py`) and step 1.3 (apply
rules, `src/brain/picks.py`) are done. The backtest report (step 1.4)
is not built yet.

## Setup

Needs Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the tests

```bash
pytest -q
```

## Download NBA data

Downloads regular-season player game logs from NBA.com (with `nba_api`),
adds the team's final score margin to each row, and saves
`data/games.parquet`. Run it on your own computer: NBA.com often blocks
cloud servers.

```bash
python -m src.data.download_games                          # all seasons in src/config.py
python -m src.data.download_games --seasons 2024-25 2025-26
```

When you choose some seasons, only those seasons are replaced in
`data/games.parquet`; the other seasons stay. A full download takes
about 30 seconds (10 calls, 2 seconds apart).

## Settings

All numbers used by the rules (lines, ratios, minimum odds, and so on)
live in `src/config.py`. Change them there, never in the logic.

## Project structure

```
bounceback-predictor/
├── docs/PRD.md          # rules and plan (single source of truth)
├── pyproject.toml       # pytest settings
├── requirements.txt
├── src/
│   ├── config.py        # all settings
│   ├── data/            # fetching NBA data and Kalshi prices
│   ├── brain/           # rules: features, eligibility, trigger, line choice
│   ├── backtest/        # backtest runner and report
│   └── live/            # daily predictions and settlement (later phases)
├── tests/
├── data/                # downloaded data and outputs (not committed)
├── api/                 # FastAPI (Phase 5)
└── web/                 # Next.js (Phase 5)
```
