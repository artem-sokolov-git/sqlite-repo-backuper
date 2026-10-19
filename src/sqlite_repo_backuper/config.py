import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from .compress import COMPRESSIONS
from .health import health_path


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    db_paths: tuple[Path, ...]
    repo: str
    token: str
    keep_days: int = 7
    keep_weeks: int = 4
    keep_months: int = 6
    schedule: str = "@daily"
    backup_on_start: bool = False
    timezone: tzinfo = field(default_factory=lambda: ZoneInfo("UTC"))
    health_file: Path = field(default_factory=lambda: health_path({}))
    compression: str = "gzip"
    age_recipient: str | None = None
    age_identity: str | None = None
    webhook_url: str | None = None


def _get_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = _get(env, name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from None
    if value < 0:
        raise ConfigError(f"{name} must be >= 0, got {value}")
    return value


def _get_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _get(env, name)
    if raw is None:
        return default
    if raw.lower() in ("1", "true", "yes", "on"):
        return True
    if raw.lower() in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be true or false, got {raw!r}")


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
    names = [p.name for p in db_paths]
    if duplicates := sorted({n for n in names if names.count(n) > 1}):
        # the file name becomes the release asset name, so it must be unique
        raise ConfigError(f"SQLITE_DB_PATHS has several files named {', '.join(duplicates)}")
    if repo.count("/") > 1 or repo.startswith("/") or repo.endswith("/"):
        raise ConfigError(f"GITHUB_REPO must be 'name' or 'owner/name', got {repo!r}")

    schedule = _get(env, "SCHEDULE") or "@daily"
    if not croniter.is_valid(schedule):
        raise ConfigError(f"SCHEDULE is not a valid cron expression: {schedule!r}")
    tz_name = _get(env, "TZ") or "UTC"
    try:
        timezone = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"unknown TZ: {tz_name!r}") from None

    compression = (_get(env, "COMPRESSION") or "gzip").lower()
    if compression not in COMPRESSIONS:
        raise ConfigError(
            f"COMPRESSION must be one of {', '.join(COMPRESSIONS)}, got {compression!r}"
        )
    webhook_url = _get(env, "WEBHOOK_URL")
    if webhook_url and not webhook_url.startswith(("http://", "https://")):
        raise ConfigError("WEBHOOK_URL must be an http(s) URL")

    return Config(
        db_paths=db_paths,
        repo=repo,
        token=token,
        keep_days=_get_int(env, "BACKUP_KEEP_DAYS", 7),
        keep_weeks=_get_int(env, "BACKUP_KEEP_WEEKS", 4),
        keep_months=_get_int(env, "BACKUP_KEEP_MONTHS", 6),
        schedule=schedule,
        backup_on_start=_get_bool(env, "BACKUP_ON_START", False),
        timezone=timezone,
        health_file=health_path(env),
        compression=compression,
        age_recipient=_get(env, "AGE_RECIPIENT"),
        age_identity=_get(env, "AGE_IDENTITY"),
        webhook_url=webhook_url,
    )
