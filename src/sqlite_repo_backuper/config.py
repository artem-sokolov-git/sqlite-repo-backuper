import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    db_paths: tuple[Path, ...]
    repo: str
    token: str


def _get(env: Mapping[str, str], name: str) -> str | None:
    """Read NAME, or the contents of the file named by NAME_FILE."""
    file_path = env.get(f"{name}_FILE")
    if file_path:
        try:
            return Path(file_path).read_text().strip()
        except OSError as e:
            raise ConfigError(f"cannot read {name}_FILE={file_path}: {e}") from e
    value = env.get(name)
    return value.strip() if value else None


def load_config(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env

    raw_paths = _get(env, "SQLITE_DB_PATHS")
    repo = _get(env, "GITHUB_REPO")
    token = _get(env, "GH_TOKEN")

    missing = [
        name
        for name, value in (
            ("SQLITE_DB_PATHS", raw_paths),
            ("GITHUB_REPO", repo),
            ("GH_TOKEN", token),
        )
        if not value
    ]
    if missing:
        raise ConfigError(f"missing required env: {', '.join(missing)}")

    db_paths = tuple(Path(p.strip()) for p in raw_paths.split(",") if p.strip())
    if not db_paths:
        raise ConfigError("SQLITE_DB_PATHS is empty")
    if repo.count("/") > 1 or repo.startswith("/") or repo.endswith("/"):
        raise ConfigError(f"GITHUB_REPO must be 'name' or 'owner/name', got {repo!r}")

    return Config(db_paths=db_paths, repo=repo, token=token)
