"""Tests for src/backtest/save.py and the saving part of run.py (PRD step 1.5)."""

import duckdb
import pandas as pd
import pytest

from src import config
from src.backtest import run
from src.backtest.save import write_duckdb
from tests.helpers import synthetic_games

TABLES = {"games", "picks", "summary", "comparisons"}


@pytest.fixture(scope="module")
def backtest():
    games = synthetic_games()
    r = run.run_backtest(games)
    return games, r.picks, r.summary, r.comparisons


@pytest.fixture
def out_dir(tmp_path):
    """Run the full command once into a temp folder."""
    games_path = tmp_path / "games.parquet"
    synthetic_games().to_parquet(games_path, index=False)
    out = tmp_path / "out"
    run.main(["--games", str(games_path), "--out-dir", str(out), "--prices", str(tmp_path / "none.parquet")])
    return out


def query(path, sql):
    con = duckdb.connect(str(path), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_all_files_written_and_no_temp_files(out_dir):
    expected = {config.REPORT_FILE, config.PICKS_FILE, config.SUMMARY_FILE,
                config.COMPARISONS_FILE, config.DUCKDB_FILE}
    assert {p.name for p in out_dir.iterdir()} == expected


def test_picks_parquet_round_trip(out_dir, backtest):
    _, picks, _, _ = backtest
    saved = pd.read_parquet(out_dir / config.PICKS_FILE)
    pd.testing.assert_frame_equal(saved, picks)
    assert saved["confidence"].isna().any()  # empty confidence kept as empty


def test_csv_files_have_all_rows(out_dir, backtest):
    _, _, summary, comparisons = backtest
    saved_summary = pd.read_csv(out_dir / config.SUMMARY_FILE)
    saved_comparisons = pd.read_csv(out_dir / config.COMPARISONS_FILE)
    assert len(saved_summary) == len(summary)
    assert list(saved_summary.columns) == list(summary.columns)
    assert len(saved_comparisons) == len(comparisons)
    assert list(saved_comparisons.columns) == list(comparisons.columns)


def test_duckdb_has_the_tables_with_right_row_counts(out_dir, backtest):
    games, picks, summary, comparisons = backtest
    db = out_dir / config.DUCKDB_FILE
    names = {row[0] for row in query(db, "SELECT table_name FROM information_schema.tables")}
    assert names == TABLES
    expected = {"games": len(games), "picks": len(picks), "summary": len(summary), "comparisons": len(comparisons)}
    for table, n in expected.items():
        assert query(db, f"SELECT COUNT(*) FROM {table}")[0][0] == n


def test_running_twice_replaces_not_appends(tmp_path, out_dir, backtest):
    games_path = tmp_path / "games.parquet"
    run.main(["--games", str(games_path), "--out-dir", str(out_dir), "--prices", str(tmp_path / "none.parquet")])
    _, picks, _, _ = backtest
    assert query(out_dir / config.DUCKDB_FILE, "SELECT COUNT(*) FROM picks")[0][0] == len(picks)
    assert len(pd.read_parquet(out_dir / config.PICKS_FILE)) == len(picks)


def test_sql_hit_rate_matches_summary(out_dir, backtest):
    _, _, summary, _ = backtest
    row = summary[(summary["line_rule"] == "fixed_gap") & (summary["section"] == "1_overview")
                  & (summary["group"] == "all") & (summary["subset"] == "brain")].iloc[0]
    sql_rate = query(out_dir / config.DUCKDB_FILE, """
        SELECT AVG(CASE WHEN hit THEN 1.0 ELSE 0.0 END)
        FROM picks WHERE line_rule = 'fixed_gap' AND is_brain
    """)[0][0]
    assert sql_rate == pytest.approx(row["hit_rate"])


def test_write_duckdb_removes_leftover_temp_file(tmp_path):
    path = tmp_path / "x.duckdb"
    (tmp_path / ".x.duckdb.tmp").write_text("garbage from a crashed run")
    write_duckdb({"t": pd.DataFrame({"a": [1, 2]})}, path)
    assert query(path, "SELECT SUM(a) FROM t")[0][0] == 3
    assert [p.name for p in tmp_path.iterdir()] == ["x.duckdb"]
