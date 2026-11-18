# PRD: Bounceback Predictor

## 1. Overview

**Bounceback Predictor** (repo: `bounceback-predictor`) is a model that predicts NBA
player points using my own way of thinking:
**a good scorer who had a bad game will bounce back in the next game.**

Predictions are made on **Kalshi player-points lines** (10+, 15+, 20+, 25+, 30+, 35+).
The goal is to test honestly whether this idea beats the market, and to build a
clean, well-tested project for my resume. If results are strong, it may become
public later.

## 2. Goals and success metrics

### Goals

1. Turn my betting logic into exact, testable rules ("the brain").
2. Test the brain on past seasons without cheating (no future data).
3. Track live predictions with real Kalshi prices (paper trading, no real money).
4. Show results in a web dashboard.

### Key definitions

| Term                     | Meaning                                                                           |
| ------------------------ | --------------------------------------------------------------------------------- |
| Hit rate                 | Correct picks ÷ total picks                                                       |
| Kalshi price             | Price of YES in cents (55¢ = market thinks 55% chance)                            |
| Decimal odds             | 1 ÷ price (55¢ → 1.82)                                                            |
| Break-even hit rate      | 1 ÷ odds (odds 1.7 → 58.8%)                                                       |
| Profit per pick (1 unit) | Win: (1 ÷ price) − 1. Loss: −1                                                    |
| ROI                      | Total profit ÷ number of picks                                                    |
| Baseline                 | Same players and same line rule, but on **every** game, not only after a bad game |
| Max price                | Highest Kalshi price where a pick type still makes money = hit rate − fee buffer  |

### Success means

- The brain's hit rate is **higher than the baseline** (this proves the bounce-back idea adds value).
- Live paper trading shows **positive ROI over 300+ picks**.
- Monthly report format: "Last month: 22/30 correct (73%), average odds 1.70, +7.4 units, ROI +24.7%".

## 3. Scope

### In scope (v1)

- League: NBA, regular season
- Market: **player points only**
- Lines: Kalshi thresholds only: 10, 15, 20, 25, 30, 35 (no 12.5 or 17.5). 10 is the minimum.
- Players: starters, plus a 6th man with a good scoring average

### Out of scope (later versions)

- Rebounds, assists, other stats
- Opponent analysis (points vs this team last time, defense, who is guarding him)
- Playoffs
- Real-money trading or any automatic order placement
- Machine learning models (v1 is rule-based)

## 4. The brain: v1 rules

### 4.1 Player pool

A player is eligible for a game if **all** of these are true:

1. He is in the **top 5 on his team by average minutes** this season, OR he is the
   **6th player by minutes and averages 15+ points**.
2. He has played **at least 10 games** this season.
3. His season average is **below 30 points**. (Players like Luka or Shai are skipped:
   for them, 25 points is still a good game, so "bad game" has a different meaning.)
4. Live use only: he is **not listed Out or Doubtful** on the NBA injury report.

### 4.2 Trigger: bad game

- **Bad game:** last game points ≤ **60%** of his season average.
- Low minutes do **not** cancel the pick. Low minutes can come from a blowout (the coach
  rests stars) or an injury. If he was injured, he usually won't play the next game, and
  the injury report check removes him.

### 4.3 Confidence

- 1 bad game → **normal** pick
- 2+ bad games in a row → **strong** pick

### 4.4 Line choice (two rules, compared in the backtest)

- **Rule A, `fixed_gap`:** highest Kalshi line that is at least **3 points below** the season average.
  - Avg 23 → 20+. Avg 26 → 20+. Avg 28 → 25+. Avg 31 → excluded (30+ cutoff).
- **Rule B, `history_70`:** highest Kalshi line the player reached in at least **70%**
  of his games this season. This makes the line depend on how consistent the player is.
  - Steady player averaging 28 (24, 27, 30, 26, 29…) → 25+
  - Up-and-down player averaging 28 (15, 38, 22, 41, 19…) → a lower line
- If no line fits, there is no pick.

### 4.5 Decision (live)

- Buy YES (paper) only if **Kalshi price ≤ max price** for that pick type
  (from backtest hit rate minus fee buffer).

### 4.6 Settings

All numbers must live in one config file. Never hard-code them in logic.

| Setting             | Value                                   |
| ------------------- | --------------------------------------- |
| LINES               | 10, 15, 20, 25, 30, 35                  |
| TOP_N_BY_MINUTES    | 5                                       |
| SIXTH_MAN_MIN_AVG   | 15.0                                    |
| MIN_GAMES_PLAYED    | 10                                      |
| MAX_SEASON_AVG      | 30.0 (exclusive)                        |
| BAD_GAME_RATIO      | 0.60                                    |
| FIXED_GAP           | 3.0                                     |
| HISTORY_HIT_RATE    | 0.70                                    |
| LOW_MINUTES_RATIO   | 0.75 (saved for analysis only)          |
| BLOWOUT_MARGIN      | 20 (saved for analysis only)            |
| FEE_BUFFER_CENTS    | 2 (check Kalshi's current fee schedule) |
| PRICE_SNAPSHOT_TIME | 60 minutes before tip-off               |

### 4.7 No-cheating rule (very important)

Every value used to make a pick (season average, last game, previous game, minutes rank,
line hit rates) must be calculated **only from games before that game**.
The game's own points are used **only** to check if the pick won.

## 5. Data sources

| Data                  | Source                                                              | Notes                                                                          |
| --------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Player game logs      | `nba_api` (`LeagueGameLog`, player mode)                            | One call per season. NBA.com may block cloud servers, so run locally.          |
| Team score margin     | `nba_api` (`LeagueGameLog`, team mode)                              | Team PLUS_MINUS = final margin. Used for the "blowout" flag.                   |
| Injury report         | Official NBA injury report                                          | Phase 3. Skip Out / Doubtful.                                                  |
| Kalshi prices         | Kalshi public API (`https://api.elections.kalshi.com/trade-api/v2`) | Market data needs no login. Logging in is only for trading, which we don't do. |
| Kalshi contract rules | Kalshi NBA points contract terms (NBAPTS)                           | Check what happens if a player doesn't play.                                   |

## 6. Tech stack

| Part               | Tool                                                             |
| ------------------ | ---------------------------------------------------------------- |
| Language           | Python 3.11+                                                     |
| Data work          | pandas, Parquet files                                            |
| Research database  | DuckDB (backtests, analysis)                                     |
| Live database      | PostgreSQL (Docker locally, Neon for hosting). **Not Supabase.** |
| ORM and migrations | SQLAlchemy + Alembic                                             |
| API                | FastAPI                                                          |
| Frontend           | Next.js (React)                                                  |
| Scheduling         | cron or GitHub Actions                                           |
| Tests              | pytest                                                           |

## 7. Project structure (suggested)

```
bounceback-predictor/
├── docs/PRD.md
├── CLAUDE.md              # not committed (in .gitignore)
├── .gitignore
├── requirements.txt
├── README.md
├── src/
│   ├── config.py          # all settings
│   ├── data/              # fetching NBA data and Kalshi prices
│   ├── brain/             # rules: features, eligibility, trigger, line choice
│   ├── backtest/          # backtest runner and report
│   └── live/              # daily predictions and settlement (later phases)
├── tests/
├── data/                  # not committed
├── api/                   # FastAPI (Phase 5)
└── web/                   # Next.js (Phase 5)
```

`.gitignore` must include from the first commit: `CLAUDE.md`, `data/`, `.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `node_modules/`.

## 8. Phases

Work on **one phase at a time**. Do not start the next phase until the current one is done
and I say so.

---

### Phase 0: Project setup

- Create the folder structure, `.gitignore`, `requirements.txt`, `README.md`, and the config file.
- Set up a virtual environment and pytest.

**Done when:** `pytest` runs (even with zero tests), and `CLAUDE.md` and `data/` are ignored by git.

---

### Phase 1: Historical backtest (full detail)

**1.1 Download data**

- Download regular-season player game logs and team game logs for
  **2021-22, 2022-23, 2023-24, 2024-25, 2025-26** with `nba_api`.
- Join the team margin to each player row (`GAME_ID` + `TEAM_ID`).
- Keep: season, game id, game date, player id, player name, team id, team abbreviation,
  matchup, W/L, minutes, points, FGA, FGM, team margin.
- Retry on timeout, and wait 2 seconds between calls.
- Save as `data/games.parquet`. Allow choosing seasons from the command line.

**1.2 Build features (no future data)**
For each player-game (grouped by player + season, sorted by date):

- `games_before`, `avg_pts`, `avg_min` (earlier games only)
- `last_pts`, `last_min`, `last_team_margin`, `prev2_pts`
- `hit_{line}` for each Kalshi line: share of earlier games where he reached that line
- `min_rank`: rank inside his team for that game by `avg_min` (1 = most minutes)

**1.3 Apply rules**

- Eligibility (4.1), trigger (4.2), confidence (4.3), both line rules (4.4).
- Also create **baseline** picks: same eligibility and line rule, no trigger.
- Flags for analysis: `low_minutes` (last game minutes < 75% of avg), `blowout` (|last team margin| ≥ 20).
- `hit` = points ≥ line.

**1.4 Report** (printed and saved)
For each line rule, show picks, wins, hit rate, max price and the 95% range of the hit rate:

1. Brain (normal, strong) vs baseline
2. Brain picks by line (10+, 15+, 20+, …)
3. By bad-game reason (low minutes, blowout)
4. By season (is it stable?)
5. Example picks

**1.5 Save outputs**

- `data/picks.parquet`, `data/summary.csv`
- DuckDB file `data/nba.duckdb` with tables `games`, `picks`, `summary`

**1.6 Acceptance tests (pytest)**

1. **Lillard example:** 12 games around 24–25 points, then 9 points → next game is a **normal** pick on **20+**.
2. **Two bad games:** two bad games in a row → **strong** pick.
3. **High scorer skipped:** a player averaging ~39 who scored 10 → **no pick**.
4. **No future data:** `avg_pts` for a game does not include that game's points.
5. **History rule depends on the player:** a steady 28-ppg player gets 25+; an up-and-down player gets a lower line.
6. **Fewer than 10 games:** no pick.
7. **Bench player:** rank 7 by minutes with a 16 ppg average → no pick.

Also include a small **fake data generator** with the same columns, so the full pipeline can be tested without internet.

**Done when:** all tests pass, the backtest runs end-to-end on real data, and the report shows brain vs baseline for both line rules.

---

### Phase 2: Daily Kalshi price collection

- Find today's Kalshi NBA player-points markets with the public API.
- Match Kalshi player names to NBA player IDs (handle accents and name differences).
- Save a price snapshot **60 minutes before each game's tip-off**: ticker, player, line, yes bid, yes ask, last price, volume, time.
- Run automatically every day (cron or GitHub Actions).
- Save to Parquet/DuckDB first (Postgres comes in Phase 4).

**Done when:** prices are collected automatically for 7 days in a row with no missing games and no unmatched players.

---

### Phase 3: Daily predictions

- Each morning: download last night's games and update the features.
- Check the injury report and skip Out / Doubtful.
- Create today's picks: player, game, line, confidence, reason (e.g. "avg 23.4, last game 9 pts, 2 bad games in a row").
- After the price snapshot: compare the price with max price → decision BUY or SKIP.
- Save every pick **before tip-off**, with a timestamp.

**Done when:** the script produces today's picks with prices and decisions, end-to-end, with no manual steps.

---

### Phase 4: PostgreSQL and paper-trading log

- PostgreSQL with SQLAlchemy + Alembic migrations.
- Tables: `players`, `teams`, `games`, `player_game_stats`, `kalshi_markets`, `price_snapshots`, `predictions`, `results`.
- Paper trading: 1 unit per BUY pick at the snapshot price.
- Next morning: settle picks (win/loss, profit) automatically.
- Monthly report: picks, correct, hit rate, average odds, break-even hit rate, profit (units), ROI, strong vs normal.
- Docker Compose for local Postgres; Neon for hosting.

**Done when:** a full day runs automatically (collect → predict → settle) and the monthly report is correct when checked by hand.

---

### Phase 5: Web dashboard

- FastAPI backend: endpoints for today's picks, pick history, monthly report, profit over time.
- Next.js frontend:
  - **Today:** picks with line, confidence, price, decision and the reason ("why the brain chose this")
  - **History:** all past picks with results, plus filters (month, confidence, line)
  - **Results:** monthly report and a profit chart over time
- Deploy (for example Vercel for the frontend; Railway or Render for the API; Neon for the database).

**Done when:** the dashboard is live at a URL and shows real paper-trading results.

## 9. Risks and notes

- **Beating the market is hard.** A negative result is still a valid result if it's measured honestly.
- **Small samples lie.** Don't trust results from fewer than ~300 picks. Always show the 95% range.
- **Future data in the backtest** makes results look fake-good. The no-cheating rule must be tested.
- **Kalshi history is short** for player-points markets. Start Phase 2 price collection as early as possible.
- **Player didn't play:** check Kalshi's contract rules for how these markets settle.
- **Legal:** publishing or selling picks has rules that differ by state and country. Check before going public.
