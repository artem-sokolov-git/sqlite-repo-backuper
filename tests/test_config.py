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


def test_schedule_defaults_and_overrides():
    base = {"SQLITE_DB_PATHS": "/a.db", "GITHUB_REPO": "r", "GH_TOKEN": "t"}
    cfg = load_config(base)
    assert (cfg.schedule, cfg.backup_on_start, cfg.keep_days) == ("@daily", False, 7)
    cfg = load_config(
        {**base, "SCHEDULE": "0 3 * * *", "BACKUP_ON_START": "true", "TZ": "Europe/Berlin"}
    )
    assert cfg.schedule == "0 3 * * *"
    assert cfg.backup_on_start is True
    assert str(cfg.timezone) == "Europe/Berlin"


@pytest.mark.parametrize(
    ("name", "value"),
    [("SCHEDULE", "bogus"), ("TZ", "Mars/Base"), ("BACKUP_ON_START", "maybe"),
     ("BACKUP_KEEP_DAYS", "-1")],
)  # fmt: skip
def test_invalid_values(name, value):
    env = {"SQLITE_DB_PATHS": "/a.db", "GITHUB_REPO": "r", "GH_TOKEN": "t", name: value}
    with pytest.raises(ConfigError, match=name):
        load_config(env)
