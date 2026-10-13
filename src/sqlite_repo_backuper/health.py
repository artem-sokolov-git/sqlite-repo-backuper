import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_HEALTH_FILE = "/tmp/sqlite-repo-backuper.health"


def health_path(env: Mapping[str, str]) -> Path:
    return Path(env.get("HEALTH_FILE") or DEFAULT_HEALTH_FILE)


def write_deadline(path: Path, deadline: datetime) -> None:
    """Record the moment after which the daemon is considered unhealthy."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(deadline.astimezone(UTC).isoformat())
    os.replace(tmp, path)


def is_healthy(path: Path, now: datetime | None = None) -> bool:
    try:
        deadline = datetime.fromisoformat(path.read_text().strip())
    except (OSError, ValueError):
        return False
    return (now or datetime.now(UTC)) <= deadline
