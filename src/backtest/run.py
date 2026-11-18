"""Run the full backtest: games -> features -> picks -> report (PRD steps 1.2-1.4).

Usage:
    python -m src.backtest.run
"""

import argparse
from pathlib import Path

import pandas as pd

from src import config
from src.backtest.compare import build_comparisons
from src.backtest.report import build_summary, format_report
from src.brain.features import build_features
from src.brain.picks import make_picks


def run_backtest(games: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    """Return (picks, summary, comparisons, report text)."""
    picks = make_picks(build_features(games))
    summary = build_summary(picks)
    comparisons = build_comparisons(picks)
    return picks, summary, comparisons, format_report(summary, comparisons, picks)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the bounce-back backtest.")
    parser.add_argument("--games", type=Path, default=config.GAMES_PATH, help="Input games Parquet file")
    parser.add_argument("--report", type=Path, default=config.REPORT_PATH, help="Where to save the report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if not args.games.exists():
        raise SystemExit(f"{args.games} not found. Run: python -m src.data.download_games")
    *_, text = run_backtest(pd.read_parquet(args.games))
    print(text)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text)
    print(f"\nReport saved to {args.report}")


if __name__ == "__main__":
    main()
