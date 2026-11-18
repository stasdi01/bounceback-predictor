"""Run the full backtest: games -> features -> picks -> report -> saved outputs.

PRD steps 1.2 to 1.5 and 1.7 (section 9 uses data/kalshi_prices.parquet if it exists).

Usage:
    python -m src.backtest.run
    python -m src.backtest.run --out-dir some/folder
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src import config
from src.backtest.compare import build_comparisons
from src.backtest.kalshi_profit import KalshiResult, kalshi_analysis
from src.backtest.report import build_summary, format_report
from src.backtest.save import save_outputs
from src.brain.features import build_features
from src.brain.picks import make_picks


@dataclass
class BacktestResult:
    picks: pd.DataFrame
    summary: pd.DataFrame
    comparisons: pd.DataFrame
    kalshi: KalshiResult | None
    report: str


def run_backtest(games: pd.DataFrame, prices: pd.DataFrame | None = None) -> BacktestResult:
    picks = make_picks(build_features(games))
    summary = build_summary(picks)
    comparisons = build_comparisons(picks)
    kalshi = kalshi_analysis(picks, prices) if prices is not None else None
    text = format_report(summary, comparisons, picks, kalshi)
    return BacktestResult(picks, summary, comparisons, kalshi, text)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the bounce-back backtest.")
    parser.add_argument("--games", type=Path, default=config.GAMES_PATH, help="Input games Parquet file")
    parser.add_argument("--prices", type=Path, default=config.KALSHI_PRICES_PATH,
                        help="Kalshi prices Parquet file (section 9 is skipped if missing)")
    parser.add_argument("--out-dir", type=Path, default=config.DATA_DIR, help="Folder for all outputs")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if not args.games.exists():
        raise SystemExit(f"{args.games} not found. Run: python -m src.data.download_games")
    games = pd.read_parquet(args.games)
    prices = pd.read_parquet(args.prices) if args.prices.exists() else None
    result = run_backtest(games, prices)
    print(result.report)
    paths = save_outputs(args.out_dir, games, result, prices)
    print("\nSaved:")
    for path in paths.values():
        print(f"  {path}")


if __name__ == "__main__":
    main()
