import gzip
import hashlib
import shutil
import sqlite3
from pathlib import Path


class SnapshotError(Exception):
    pass


def snapshot(source: Path, dest: Path) -> None:
    """Consistent copy of a live database (WAL-safe) verified with integrity_check."""
    if not source.is_file():
        raise SnapshotError(f"database not found: {source}")

    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    except sqlite3.Error as e:
        raise SnapshotError(f"backup of {source} failed: {e}") from e
    finally:
        src.close()

    check = sqlite3.connect(dest)
    try:
        result = check.execute("PRAGMA integrity_check").fetchall()
    finally:
        check.close()
    if result != [("ok",)]:
        raise SnapshotError(f"integrity_check failed for {source}: {result}")


def gzip_file(source: Path, dest: Path) -> None:
    with source.open("rb") as f_in, gzip.open(dest, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
