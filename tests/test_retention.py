from datetime import UTC, datetime, timedelta

from sqlite_repo_backuper.retention import Backup, make_tag, parse_tag, select_to_delete


def _backup(created: datetime) -> Backup:
    return Backup(make_tag(created), created)


def _deleted_tags(backups, **limits):
    return {b.tag for b in select_to_delete(backups, **limits)}


def test_tag_roundtrip():
    created = datetime(2026, 10, 13, 15, 26, 28, tzinfo=UTC)
    assert make_tag(created) == "backup-2026-10-13T15-26-28Z"
    assert parse_tag(make_tag(created)) == Backup(make_tag(created), created)


def test_parse_foreign_tag():
    assert parse_tag("v1.0.0") is None


def test_empty():
    assert select_to_delete([], 7, 4, 6) == []


def test_keeps_last_backup_of_each_day():
    morning = _backup(datetime(2026, 10, 13, 3, tzinfo=UTC))
    evening = _backup(datetime(2026, 10, 13, 21, tzinfo=UTC))
    yesterday = _backup(datetime(2026, 10, 12, 21, tzinfo=UTC))
    deleted = _deleted_tags([morning, evening, yesterday], keep_days=2, keep_weeks=0, keep_months=0)
    assert deleted == {morning.tag}


def test_day_limit_counts_days_with_backups():
    start = datetime(2026, 10, 1, 3, tzinfo=UTC)
    backups = [_backup(start + timedelta(days=i)) for i in range(10)]
    deleted = select_to_delete(backups, keep_days=3, keep_weeks=0, keep_months=0)
    assert len(deleted) == 7
    assert {b.tag for b in backups[-3:]}.isdisjoint(b.tag for b in deleted)


def test_weekly_and_monthly_survive_daily_window():
    now = datetime(2026, 10, 13, 3, tzinfo=UTC)
    backups = [_backup(now - timedelta(days=i)) for i in range(120)]
    deleted = {b.tag for b in select_to_delete(backups, 7, 4, 6)}
    kept = [b for b in backups if b.tag not in deleted]
    assert len(kept) < 30
    assert backups[0] in kept  # newest
    assert all(b in kept for b in backups[:7])  # last 7 days


def test_newest_always_kept():
    only = _backup(datetime(2026, 10, 13, tzinfo=UTC))
    assert select_to_delete([only], 0, 0, 0) == []
    older = _backup(datetime(2026, 10, 1, tzinfo=UTC))
    deleted = _deleted_tags([only, older], keep_days=0, keep_weeks=0, keep_months=0)
    assert deleted == {older.tag}
