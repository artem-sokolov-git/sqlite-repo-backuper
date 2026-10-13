from pathlib import Path

import pytest

from sqlite_repo_backuper.config import ConfigError, load_config


def test_loads_from_env():
    cfg = load_config(
        {"SQLITE_DB_PATHS": "/data/a.db, /data/b.db", "GITHUB_REPO": "o/r", "GH_TOKEN": "t"}
    )
    assert cfg.db_paths == (Path("/data/a.db"), Path("/data/b.db"))
    assert cfg.repo == "o/r"
    assert cfg.token == "t"


def test_token_from_file(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("secret\n")
    cfg = load_config(
        {"SQLITE_DB_PATHS": "/a.db", "GITHUB_REPO": "r", "GH_TOKEN_FILE": str(token_file)}
    )
    assert cfg.token == "secret"


def test_missing_required():
    with pytest.raises(ConfigError, match="SQLITE_DB_PATHS, GITHUB_REPO, GH_TOKEN"):
        load_config({})


def test_bad_repo():
    with pytest.raises(ConfigError, match="GITHUB_REPO"):
        load_config({"SQLITE_DB_PATHS": "/a.db", "GITHUB_REPO": "a/b/c", "GH_TOKEN": "t"})
