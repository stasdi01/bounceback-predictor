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


def save_outputs(
    out_dir: Path,
    games: pd.DataFrame,
    picks: pd.DataFrame,
    summary: pd.DataFrame,
    comparisons: pd.DataFrame,
    report: str,
) -> dict[str, Path]:
    """Write all backtest outputs into `out_dir`. Returns the written paths."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "report": out_dir / config.REPORT_FILE,
        "picks": out_dir / config.PICKS_FILE,
        "summary": out_dir / config.SUMMARY_FILE,
        "comparisons": out_dir / config.COMPARISONS_FILE,
        "duckdb": out_dir / config.DUCKDB_FILE,
    }
    write_text(report, paths["report"])
    write_parquet(picks, paths["picks"])
    write_csv(summary, paths["summary"])
    write_csv(comparisons, paths["comparisons"])
    write_duckdb(
        {"games": games, "picks": picks, "summary": summary, "comparisons": comparisons},
        paths["duckdb"],
    )
    return paths
