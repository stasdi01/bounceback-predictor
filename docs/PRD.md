# PRD: Bounceback Predictor

## 1. Overview

**Bounceback Predictor** (repo: `bounceback-predictor`) is a model that predicts NBA
player points using my own way of thinking:
**a good scorer who had a bad game will bounce back in the next game.**

Predictions are made on **Kalshi player-points lines** (10+, 15+, 20+, 25+, 30+, 35+).
The goal is to test honestly whether this idea makes money, and to build a clean,
well-tested project for my resume. If results are strong, it may become public later.

This document is the **single source of truth**. If code and PRD disagree, the PRD wins
(or the PRD gets updated after a decision; see the Decision log at the end).

## 2. Goals and success metrics

### Goals

1. Turn my betting logic into exact, testable rules ("the brain").
2. Test the brain on past seasons without cheating (no future data).
3. Track live predictions with real Kalshi prices (paper trading, no real money).
4. Show every prediction and the results in a web dashboard.

### Key definitions

| Term                | Meaning                                                                                                  |
| ------------------- | -------------------------------------------------------------------------------------------------------- |
| Kalshi price        | Price of YES in dollars (0.65 = 65¢). Stored, but not shown to the user.                                 |
| Odds                | Decimal odds = 1 ÷ price (0.65 → 1.54). **Odds are shown everywhere**, not prices.                       |
| Hit rate            | Correct picks ÷ total picks                                                                              |
| Break-even hit rate | 1 ÷ odds. The % of picks you must win to not lose money (odds 1.70 → 58.8%).                             |
| Stake               | Amount put on one pick, as % of the monthly budget                                                       |
| Profit per pick     | Win: stake × (odds − 1). Loss: −stake.                                                                   |
| Monthly profit %    | Sum of profit of all picks in the month, as % of the starting budget                                     |
| Baseline            | Same players and same line rule, but on **every** game, not only after a bad game                        |
| Max price           | Highest price where a pick type still makes money: `max_price_cents = hit_rate × 100 − FEE_BUFFER_CENTS` |

### Success means

1. **The brain beats the baseline.** Bounce-back picks hit more often than the same players on every game.
2. **Monthly profit is positive over 300+ picks** in live paper trading. One month can be luck.

## 3. Scope

### In scope (v1)

- League: NBA, regular season
- Market: **player points only**
- Lines: Kalshi thresholds only: 10, 15, 20, 25, 30, 35 (no 12.5 or 17.5). 10 is the minimum.
- Players: anyone averaging 14 to 29.9 points this season (see 4.1)

### Out of scope (later versions)

- Rebounds, assists, other stats
- Opponent analysis (points vs this team last time, defense, who is guarding him)
- Playoffs
- Real-money trading or any automatic order placement
- Machine learning models (v1 is rule-based)

## 4. The brain: v1 rules

### 4.1 Player pool

A player is eligible for a game if **all** of these are true:

1. His season average is **14 or more** and **below 30**.
   - Below 14: not a reliable scorer.
   - 30+ (like Luka or Shai): skipped, because for them 25 points is still a good game.
2. He has played **at least 10 games** this season.
3. Live use only: he is **not listed Out or Doubtful** on the NBA injury report.

There is **no starters or minutes-rank rule**. Starters don't always score the most.

**Season average** = average points from all his games this season **before the game we predict**.
If he was traded, it includes games for all his teams this season.

### 4.2 Trigger: bad game

- **Bad game:** last game points ≤ **60%** of his season average.
- The season average used is the one **right before the game we predict** (today's average),
  for both the last game and the game before last.
- Low minutes do **not** cancel the pick. They can come from a blowout (the coach rests stars)
  or an injury. If he was injured, he usually won't play the next game, and the injury report
  check removes him.

### 4.3 Confidence

- 1 bad game → **normal** pick
- 2+ bad games in a row → **strong** pick

### 4.4 Line choice (two rules, compared in the backtest)

- **Rule A, `fixed_gap`:** highest Kalshi line that is at least **3 points below** the season average.
  - Avg 23 → 20+. Avg 26 → 20+. Avg 28 → 25+. Avg 15 → 10+.
- **Rule B, `history_70`:** highest Kalshi line the player reached in at least **70%**
  of his earlier games this season. The line depends on how consistent he is.
  - Steady player averaging 28 (24, 27, 30, 26, 29…) → 25+
  - Up-and-down player averaging 28 (15, 38, 22, 41, 19…) → a lower line
- If no line fits, there is no pick.

### 4.5 Minimum odds

- Never make a pick with **odds below 1.40** (price above ~71¢).
- If the chosen line's odds are below 1.40, **skip the player.** Do not move to another line.
- The backtest can only apply this rule if Kalshi historical prices are available (see Phase 1 end).

### 4.6 Decision (live)

A pick is made (paper only) when:

1. The player passes 4.1–4.4, and
2. Odds ≥ 1.40, and
3. Kalshi price ≤ max price for that pick type (from the backtest).

### 4.7 Pick strength and "Pick of the Night"

Each night, one pick is marked **Pick of the Night**.
The final strength score will be decided **after the Phase 1 backtest**, using the factors
that really improve the hit rate.

Candidate factors (saved for every pick in Phase 1):
| Factor | Meaning |
|---|---|
| Personal bounce-back rate | How often this player reached the line after his earlier bad games (earlier games only). An earlier bad game counts only if the brain would have triggered on it at that time (10+ games, average 14 to 29.9, last game ≤ 60% of average). Saved in two versions: **this season only** and **all earlier games in our data** (including earlier seasons). The 1.4 report shows which is more useful. |
| Unlucky bad game | Bad game with normal minutes (≥ 75% of his average) and normal shot attempts (≥ 75% of his average FGA), so the low score came from poor shooting |
| Consistency | His hit rate on the chosen line this season (earlier games only) |
| Size of the drop | Last game points ÷ season average (lower = bigger drop) |
| Two bad games in a row | Strong vs normal |

**Temporary order until then:** strong before normal → lowest (last game ÷ season average) → higher odds.

**How the strength score is chosen:** using seasons **2021-22 to 2023-24** only, then checked
on **2024-25 and 2025-26**. This avoids choosing and testing on the same data.

### 4.8 No-cheating rule (very important)

Every value used to make a pick (season average, last game, game before last, line hit rates,
strength factors) must be calculated **only from games before that game**.
The game's own points are used **only** to check if the pick won.

### 4.9 Settings

All numbers live in one config file. Never hard-code them in logic.

| Setting             | Value                                   |
| ------------------- | --------------------------------------- |
| LINES               | 10, 15, 20, 25, 30, 35                  |
| MIN_SEASON_AVG      | 14.0 (inclusive)                        |
| MAX_SEASON_AVG      | 30.0 (exclusive)                        |
| MIN_GAMES_PLAYED    | 10                                      |
| BAD_GAME_RATIO      | 0.60                                    |
| FIXED_GAP           | 3.0                                     |
| HISTORY_HIT_RATE    | 0.70                                    |
| MIN_ODDS            | 1.40                                    |
| STAKE_PERCENT       | 10 (of the starting monthly budget)     |
| UNLUCKY_MIN_RATIO   | 0.75                                    |
| UNLUCKY_FGA_RATIO   | 0.75                                    |
| LOW_MINUTES_RATIO   | 0.75 (saved for analysis only)          |
| BLOWOUT_MARGIN      | 20 (saved for analysis only)            |
| FEE_BUFFER_CENTS    | 2 (check Kalshi's current fee schedule) |
| PRICE_SNAPSHOT_MINUTES_BEFORE | 60 (minutes before tip-off)   |
| SEASONS             | 2021-22, 2022-23, 2023-24, 2024-25, 2025-26 |
| REQUEST_DELAY_SECONDS | 2                                     |
| MAX_RETRIES         | 3 (total tries per API call)            |
| REQUEST_TIMEOUT_SECONDS | 60                                  |
| CI_Z                | 1.96 (95% range of the hit rate)        |
| MIN_RELIABLE_PICKS  | 300 (fewer picks = marked "small sample") |
| STRENGTH_BUCKETS    | 3 (low / mid / high groups in the report) |
| DAYS_SINCE_BINS     | 1, 2, 4, 8 (groups 1 / 2–3 / 4–7 / 8+)  |
| REPORT_EXAMPLE_PICKS | 10                                     |
| REPORT_SEED         | 42                                      |
| END_OF_SEASON_DAYS  | 7 (analysis only, not a rule)           |

## 5. Money tracking (paper trading)

There are **two tracks**, each with its **own separate budget**:

1. **All picks:** every pick the brain makes
2. **Pick of the Night:** only the one strongest pick each night

Rules for each track:

- Each month starts with a **100% budget**.
- Each pick stakes **10% of the starting monthly budget** (the same stake for every pick that month).
- Profit is calculated **per pick**: win = stake × (odds − 1), loss = −stake.
- If **less than 10%** is left, stake what is left.
- If the budget reaches **0%**, stop making picks for that month. Monthly result = **−100%**.
- If there are more picks in one night than the budget allows, take the **strongest picks first** (4.7).

### Monthly report (for each track)

| Metric              | Example          |
| ------------------- | ---------------- |
| Picks               | 30               |
| Correct             | 22 (73%)         |
| Average odds        | 1.70             |
| Break-even hit rate | 58.8%            |
| Profit %            | +74%             |
| Strong vs normal    | shown separately |

## 6. Data sources

| Data                  | Source                                                              | Notes                                                                          |
| --------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Player game logs      | `nba_api` (`LeagueGameLog`, player mode)                            | One call per season. NBA.com may block cloud servers, so run locally.          |
| Team score margin     | `nba_api` (`LeagueGameLog`, team mode)                              | Team PLUS_MINUS = final margin. Used for the "blowout" flag.                   |
| Injury report         | Official NBA injury report                                          | Phase 3. Skip Out / Doubtful.                                                  |
| Kalshi prices         | Kalshi public API (`https://api.elections.kalshi.com/trade-api/v2`) | Market data needs no login. Logging in is only for trading, which we don't do. |
| Kalshi contract rules | Kalshi NBA points contract terms (NBAPTS)                           | Check what happens if a player doesn't play.                                   |

## 7. Tech stack

| Part               | Tool                                                             |
| ------------------ | ---------------------------------------------------------------- |
| Language           | Python 3.12                                                      |
| Data work          | pandas, Parquet files                                            |
| Research database  | DuckDB (backtests, analysis)                                     |
| Live database      | PostgreSQL (Docker locally, Neon for hosting). **Not Supabase.** |
| ORM and migrations | SQLAlchemy + Alembic                                             |
| API                | FastAPI                                                          |
| Frontend           | Next.js (React)                                                  |
| Scheduling         | cron or GitHub Actions                                           |
| Tests              | pytest                                                           |

## 8. Project structure

```
bounceback-predictor/
├── docs/PRD.md
├── CLAUDE.md              # not committed (in .gitignore)
├── .gitignore
├── pyproject.toml
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

`.gitignore` must include: `CLAUDE.md`, `/data/` (root folder only, so `src/data/` is still committed), `*.duckdb`, `.env`, `.venv/`, `__pycache__/`,
`.pytest_cache/`, `.ruff_cache/`, `node_modules/`, `.DS_Store`.

## 9. Phases

Work on **one phase at a time**. Don't start the next phase until the current one is done
and I say so. Phase 1 can be split into steps (1.1, 1.2, …), with one commit each.

---

### Phase 0: Project setup

- Create the folder structure, `pyproject.toml` (pytest settings), `requirements.txt`,
  `README.md`, and `src/config.py` with every setting from 4.9.
- Set up a virtual environment (Python 3.12) and pytest, with a small config sanity test.

**Done when:** `pytest -q` passes, and git ignores `CLAUDE.md` and `data/`.

---

### Phase 1: Historical backtest

**1.1 Download data**

- Download regular-season player game logs and team game logs for
  **2021-22, 2022-23, 2023-24, 2024-25, 2025-26** with `nba_api`.
- Join the team margin to each player row (`GAME_ID` + `TEAM_ID`).
- Keep: season, game id, game date, player id, player name, team id, team abbreviation,
  matchup, W/L, minutes, points, FGA, FGM, team margin.
- Retry on timeout, and wait 2 seconds between calls. Allow choosing seasons from the command line.
- Save as `data/games.parquet`. If only some seasons are downloaded, replace only those
  seasons in the file and keep the others.

**1.2 Build features (no future data)**
For each player-game (grouped by player + season, sorted by date), using earlier games only:

- `games_before`, `avg_pts`, `avg_min`, `avg_fga`
- `last_pts`, `last_min`, `last_fga`, `last_team_margin`, `prev2_pts`
- `hit_{line}` for each Kalshi line: share of earlier games where he reached that line
- Strength factors from 4.7: personal bounce-back rate, unlucky bad game, consistency,
  drop size (`last_pts / avg_pts`)
  - Personal bounce-back rate, two versions:
    `bb_count_season`, `bb_rate_season_{line}` (this season only) and
    `bb_count_all`, `bb_rate_all_{line}` (all earlier games, including earlier seasons)
  - Unlucky bad game: `normal_volume` (last game minutes and FGA both ≥ 75% of average);
    combined with the bad-game trigger in 1.3
  - Consistency: `hit_{line}` for the chosen line (picked in 1.3)
- `days_since_last_game`: days between this game and his last game this season.
  Saved for analysis only, not a rule.

**1.3 Apply rules**

- Eligibility (4.1), trigger (4.2), confidence (4.3), both line rules (4.4).
- Also create **baseline** picks: same eligibility and line rule, no trigger.
  The baseline is every eligible game, so it includes the brain picks.
- Analysis flags: `low_minutes` (last game minutes < 75% of avg), `blowout` (|last team margin| ≥ 20).
- End-of-season flags (analysis only, not a rule). The season end = last game date in our data
  for that season:
  - `end_of_season`: the pick's game is in the last 7 days of the regular season.
  - `last_game_end_of_season`: the bad game (last game) was in the last 7 days.
- `hit` = points ≥ line.

**1.4 Report** (printed and saved)
For each line rule, show picks, wins, hit rate, max price, and the 95% range of the hit rate:

1. Brain (normal, strong) vs baseline, plus one extra row: baseline on non-bad games only
2. Brain picks by line (10+, 15+, 20+, …)
3. By bad-game reason (low minutes, blowout, unlucky, end of season for the pick's game
   and for the bad game)
4. **By each strength factor** (for example personal bounce-back rate high vs low)
5. By season (is it stable?)
6. Example picks

**1.5 Save outputs**

- `data/picks.parquet`, `data/summary.csv`
- DuckDB file `data/nba.duckdb` with tables `games`, `picks`, `summary`

**1.6 Acceptance tests (pytest)**

1. **Lillard example:** 12 games around 24–25 points, then 9 points → next game is a **normal** pick on **20+**.
2. **Two bad games:** two bad games in a row → **strong** pick.
3. **High scorer skipped:** a player averaging ~39 who scored 10 → **no pick**.
4. **Low scorer skipped:** a player averaging 13.5 who had a bad game → **no pick**.
5. **No future data:** `avg_pts` for a game does not include that game's points.
6. **History rule depends on the player:** a steady 28-ppg player gets 25+; an up-and-down player gets a lower line.
7. **Fewer than 10 games:** no pick.

Also include a small **fake data generator** with the same columns, so the full pipeline can be tested without internet.

**1.7 Kalshi history check (end of Phase 1)**
Check whether Kalshi's historical API has past prices for NBA player-points markets.

- If yes: add a step to apply minimum odds and calculate backtest profit.
- If no: the backtest reports hit rates only, and money is measured from live picks.

**Done when:** all tests pass, the backtest runs end-to-end on real data, the report shows brain vs
baseline for both line rules and the hit rate for each strength factor, and the Kalshi check is done.

---

### Phase 2: Daily Kalshi price collection

- Find today's Kalshi NBA player-points markets with the public API.
- Match Kalshi player names to NBA player IDs (handle accents and name differences).
- Save a price snapshot **60 minutes before each game's tip-off**: ticker, player, line, yes bid,
  yes ask, last price, volume, time.
- Run automatically every day (cron or GitHub Actions). Save to Parquet/DuckDB first.

**Done when:** prices are collected automatically for 7 days in a row with no missing games and no unmatched players.

---

### Phase 3: Daily predictions

- Each morning: download last night's games and update the features.
- Check the injury report and skip Out / Doubtful.
- Create today's picks: player, game, line, confidence, strength factors, and the reason
  (for example "avg 23.4, last game 9 pts, 2 bad games in a row").
- After the price snapshot: calculate odds, apply minimum odds (4.5) and max price (4.6),
  then decide BUY or SKIP.
- Mark the **Pick of the Night** (4.7, using the strength score chosen after Phase 1).
- Save every pick **before tip-off**, with a timestamp.

**Done when:** the script produces today's picks with odds, decisions, and a Pick of the Night, end-to-end, with no manual steps.

---

### Phase 4: PostgreSQL and paper-trading log

- PostgreSQL with SQLAlchemy + Alembic migrations.
- Tables: `players`, `teams`, `games`, `player_game_stats`, `kalshi_markets`, `price_snapshots`,
  `predictions`, `results`, `budgets` (one per track per month).
- Money tracking exactly as in section 5, for both tracks.
- Next morning: settle picks automatically (points scored, won/lost, profit).
- Monthly report (section 5) for each track.
- Docker Compose for local Postgres; Neon for hosting.

**Done when:** a full day runs automatically (collect → predict → settle), budgets update correctly
(including the 0% stop rule), and the monthly report is correct when checked by hand.

---

### Phase 5: Web dashboard

- FastAPI backend: endpoints for today's picks, pick history, monthly reports, profit over time.
- Next.js frontend:
  - **Today:** picks with line, odds, confidence, strength, and the reason ("why the brain chose this").
    Pick of the Night highlighted.
  - **History:** **every single prediction**: date, player, game, line, odds, stake, points scored,
    result, profit. Filters: month, track, confidence, line.
  - **Results:** **two separate profit tables**, one for "All picks" and one for
    "Pick of the Night", with the monthly report for each, and a profit chart over time.
- Odds are shown everywhere, never prices.
- Deploy (for example Vercel for the frontend; Railway or Render for the API; Neon for the database).

**Done when:** the dashboard is live at a URL and shows real paper-trading results for both tracks.

## 10. Risks and notes

- **Beating the market is hard.** A negative result is still a valid result if it's measured honestly.
- **Small samples lie.** Don't trust results from fewer than ~300 picks. Always show the 95% range.
- **Future data in the backtest** makes results look fake-good. The no-cheating rule must be tested.
- **Minimum odds may remove many picks.** Safe lines often have low odds. Watch how many picks remain.
- **Player didn't play:** check Kalshi's contract rules for how these markets settle.
- **Legal:** publishing or selling picks has rules that differ by state and country. Check before going public.

## 11. Decision log

Newest at the bottom. Format: date: decision.

- 2026-11-17: v1 scope: NBA regular season, player points only, Kalshi lines 10+ to 35+.
- 2026-11-17: Database: PostgreSQL + DuckDB, not Supabase.
- 2026-11-17: Player pool: season average ≥ 14 and < 30, 10+ games. Starters / minutes rank removed.
- 2026-11-17: Bad-game checks use the season average right before the predicted game.
- 2026-11-17: Minimum odds 1.40. If too low, skip the player (don't move lines). Show odds, not prices.
- 2026-11-17: Money: 100% monthly budget, 10% of the starting budget per pick, stop at 0% (−100%).
- 2026-11-17: Two tracks with separate budgets: All picks and Pick of the Night.
- 2026-11-17: Pick strength factors decided after the Phase 1 backtest, based on data.
- 2026-11-17: Phase order unchanged. Kalshi price history checked at the end of Phase 1.
- 2026-11-17: Setting PRICE_SNAPSHOT_TIME renamed to PRICE_SNAPSHOT_MINUTES_BEFORE = 60 (a plain number).
- 2026-11-17: .gitignore uses `/data/` (root only) instead of `data/`, so code in `src/data/` is not ignored.
- 2026-11-17: Download settings added to config: SEASONS, REQUEST_DELAY_SECONDS = 2, MAX_RETRIES = 3, REQUEST_TIMEOUT_SECONDS = 60.
- 2026-11-17: Downloading some seasons replaces only those seasons in `data/games.parquet`; other seasons are kept.
- 2026-11-18: Personal bounce-back rate counts an earlier bad game only if the brain would have triggered on it then (10+ games, average 14 to 29.9, last game ≤ 60%).
- 2026-11-18: Personal bounce-back rate saved in two versions: this season only, and all earlier games including earlier seasons.
- 2026-11-18: `days_since_last_game` added as a feature, for analysis only (not a rule).
- 2026-11-18: Baseline = every eligible game, including the brain picks. The 1.4 report also shows baseline on non-bad games only.
- 2026-11-18: Report settings added: CI_Z = 1.96, MIN_RELIABLE_PICKS = 300, STRENGTH_BUCKETS = 3, DAYS_SINCE_BINS = 1, 2, 4, 8, REPORT_EXAMPLE_PICKS = 10, REPORT_SEED = 42.
- 2026-11-18: Strength score will be chosen on 2021-22 to 2023-24 and checked on 2024-25 and 2025-26.
- 2026-11-18: End-of-season analysis flags added (pick's game and bad game in the last END_OF_SEASON_DAYS = 7 days of the season). Analysis only, not a rule.
