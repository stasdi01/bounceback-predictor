# Bounceback Predictor

A rule-based model that predicts NBA player points on Kalshi lines
(10+, 15+, 20+, 25+, 30+, 35+). The idea: **a good scorer who had a bad
game will bounce back in the next game.** The project tests this idea
honestly on past seasons and with live paper trading (no real money).

Full rules and plan: [`docs/PRD.md`](docs/PRD.md).

## Status

Phase 0 (project setup) is done. Phase 1: steps 1.1 (download data),
1.2 (build features), 1.3 (apply rules), 1.4 (backtest report), 1.5
(save outputs) and 1.7 (Kalshi price history) are done. Next: 1.6
(acceptance tests and fake data generator).

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

## Download Kalshi prices (optional, for report section 9)

Kalshi has NBA player-points prices (series `KXNBAPTS`) from 2025-11-18.
This downloads, for every backtest pick that has a Kalshi market on its
line, the bid / ask / last price at tip-off − 60 minutes, and saves
`data/kalshi_prices.parquet`. No login is needed.

```bash
python -m src.data.kalshi_history                  # about 25 minutes the first time
python -m src.data.kalshi_history --max-markets 20 # quick test
```

A re-run only downloads markets that are not in the file yet. Needs
`data/games.parquet` first.

## Run the backtest

Needs `data/games.parquet` (see above). Builds features, applies the
brain rules and prints the report (brain vs baseline, by line, by
bad-game reason, by strength factor, by season, factor vs baseline in
the same group, by season average group, example picks), then saves all
outputs.

```bash
python -m src.backtest.run                     # outputs go to data/
python -m src.backtest.run --out-dir some/dir  # or another folder
```

### Outputs

Each run replaces these files (they are not committed):

| File | Content |
|---|---|
| `data/report.txt` | The printed report |
| `data/picks.parquet` | Every pick row: baseline and brain, both line rules |
| `data/summary.csv` | Report sections 1-5 as one table |
| `data/comparisons.csv` | Report sections 6-7 (brain vs baseline inside groups) |
| `data/kalshi_summary.csv` | Report section 9 (only if Kalshi prices exist) |
| `data/nba.duckdb` | Tables `games`, `picks`, `summary`, `comparisons` (+ `kalshi_prices`, `kalshi_summary`) |

Example DuckDB query (brain hit rate per line rule):

```bash
python -c "import duckdb; print(duckdb.connect('data/nba.duckdb', read_only=True).sql(\"SELECT line_rule, COUNT(*) AS picks, AVG(hit::INT) AS hit_rate FROM picks WHERE is_brain GROUP BY 1\"))"
```

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
