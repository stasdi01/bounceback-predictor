"""Save backtest outputs (PRD step 1.5).

Every file is first written to a temp file and then renamed, so a crash
never leaves a half-written file. Each run REPLACES the outputs (no appending).
"""

from pathlib import Path

import duckdb
import pandas as pd

from src import config


def _temp_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.tmp")


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    tmp = _temp_path(path)
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def write_csv(df: pd.DataFrame, path: Path) -> None:
    tmp = _temp_path(path)
    df.to_csv(tmp, index=False)
    tmp.replace(path)


def write_text(text: str, path: Path) -> None:
    tmp = _temp_path(path)
    tmp.write_text(text)
    tmp.replace(path)


def write_duckdb(tables: dict[str, pd.DataFrame], path: Path) -> None:
    """Build a fresh DuckDB file with one table per DataFrame."""
    tmp = _temp_path(path)
    tmp.unlink(missing_ok=True)  # leftover from a crashed run
    con = duckdb.connect(str(tmp))
    try:
        for name, df in tables.items():
            con.register("_df", df)
            con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM _df')
            con.unregister("_df")
    finally:
        con.close()
    tmp.replace(path)


def save_outputs(out_dir: Path, games: pd.DataFrame, result, prices: pd.DataFrame | None = None) -> dict[str, Path]:
    """Write all backtest outputs into `out_dir`. Returns the written paths.

    `result` is a run.BacktestResult. Kalshi outputs are written only if there are prices.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "report": out_dir / config.REPORT_FILE,
        "picks": out_dir / config.PICKS_FILE,
        "summary": out_dir / config.SUMMARY_FILE,
        "comparisons": out_dir / config.COMPARISONS_FILE,
    }
    write_text(result.report, paths["report"])
    write_parquet(result.picks, paths["picks"])
    write_csv(result.summary, paths["summary"])
    write_csv(result.comparisons, paths["comparisons"])
    tables = {"games": games, "picks": result.picks, "summary": result.summary, "comparisons": result.comparisons}
    if result.kalshi is not None:
        paths["kalshi_summary"] = out_dir / config.KALSHI_SUMMARY_FILE
        write_csv(result.kalshi.summary, paths["kalshi_summary"])
        tables.update({"kalshi_prices": prices, "kalshi_summary": result.kalshi.summary})
    paths["duckdb"] = out_dir / config.DUCKDB_FILE
    write_duckdb(tables, paths["duckdb"])
    return paths
