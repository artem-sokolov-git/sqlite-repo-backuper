from pathlib import Path

import pytest

from sqlite_repo_backuper import backup
from sqlite_repo_backuper.config import Config


@pytest.mark.parametrize("error", [OSError(7, "Argument list too long"), KeyError("assets")])
def test_refresh_index_never_raises(monkeypatch, caplog, error):
    class BrokenGitHub:
        def __init__(self, token):
            pass

        def resolve_repo(self, repo):
            return repo

    def broken_update(gh, repo):
        raise error

    monkeypatch.setattr(backup, "GitHub", BrokenGitHub)
    monkeypatch.setattr(backup, "update_index", broken_update)
    backup.refresh_index(Config(db_paths=(Path("/a.db"),), repo="o/r", token="t"))
    assert "could not update README backup list" in caplog.text
