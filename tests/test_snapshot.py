import sqlite3

import pytest

from sqlite_repo_backuper.snapshot import SnapshotError, snapshot


def test_snapshot_wal_database(tmp_path):
    src = tmp_path / "app.db"
    conn = sqlite3.connect(src)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(100)])
    conn.commit()  # data may still live only in the -wal file

    dest = tmp_path / "copy.db"
    snapshot(src, dest)
    conn.close()

    copy = sqlite3.connect(dest)
    assert copy.execute("SELECT count(*) FROM t").fetchone() == (100,)
    copy.close()


def test_snapshot_missing_source(tmp_path):
    with pytest.raises(SnapshotError, match="not found"):
        snapshot(tmp_path / "nope.db", tmp_path / "out.db")
