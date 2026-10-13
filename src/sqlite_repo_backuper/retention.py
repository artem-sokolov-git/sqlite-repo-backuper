from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

TAG_PREFIX = "backup-"
TAG_FORMAT = f"{TAG_PREFIX}%Y-%m-%dT%H-%M-%SZ"


@dataclass(frozen=True)
class Backup:
    tag: str
    created: datetime


def make_tag(created: datetime) -> str:
    return created.strftime(TAG_FORMAT)


def parse_tag(tag: str) -> Backup | None:
    try:
        return Backup(tag, datetime.strptime(tag, TAG_FORMAT).replace(tzinfo=UTC))
    except ValueError:
        return None


def _keep_latest_per_bucket(
    newest_first: list[Backup], bucket: Callable[[datetime], object], limit: int
) -> set[str]:
    kept: dict[object, str] = {}
    for backup in newest_first:
        key = bucket(backup.created)
        if key not in kept:
            if len(kept) == limit:
                break
            kept[key] = backup.tag
    return set(kept.values())


def select_to_delete(
    backups: Iterable[Backup], keep_days: int, keep_weeks: int, keep_months: int
) -> list[Backup]:
    """Keep the latest backup of each of the last N days/weeks/months that have backups.

    The newest backup is always kept, even if all limits are zero.
    """
    newest_first = sorted(backups, key=lambda b: b.created, reverse=True)
    if not newest_first:
        return []

    keep = {newest_first[0].tag}
    keep |= _keep_latest_per_bucket(newest_first, lambda d: d.date(), keep_days)
    keep |= _keep_latest_per_bucket(newest_first, lambda d: d.isocalendar()[:2], keep_weeks)
    keep |= _keep_latest_per_bucket(newest_first, lambda d: (d.year, d.month), keep_months)
    return [b for b in newest_first if b.tag not in keep]
