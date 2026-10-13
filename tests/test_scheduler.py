from datetime import UTC, datetime, timedelta

from sqlite_repo_backuper.config import Config
from sqlite_repo_backuper.health import is_healthy
from sqlite_repo_backuper.scheduler import HEALTH_GRACE, next_run, run_daemon


class FakeClock:
    """Stands in for both the clock and the stop event: wait() advances time."""

    def __init__(self, start: datetime, ticks: int):
        self.current = start
        self.ticks = ticks

    def now(self) -> datetime:
        return self.current

    def is_set(self) -> bool:
        return self.ticks <= 0

    def wait(self, timeout: float) -> bool:
        if self.ticks <= 0:
            return True
        self.ticks -= 1
        self.current += timedelta(seconds=timeout)
        return False


def _config(tmp_path, **kwargs) -> Config:
    return Config(
        db_paths=(),
        repo="r",
        token="t",
        schedule="0 * * * *",
        health_file=tmp_path / "health",
        **kwargs,
    )


def test_next_run():
    after = datetime(2026, 10, 13, 15, 30, tzinfo=UTC)
    assert next_run("0 * * * *", after) == datetime(2026, 10, 13, 16, tzinfo=UTC)


def test_runs_on_every_tick(tmp_path):
    clock = FakeClock(datetime(2026, 10, 13, 15, 30, tzinfo=UTC), ticks=3)
    runs = []
    run_daemon(_config(tmp_path), lambda c: runs.append(clock.now()), clock, clock.now)
    assert runs == [datetime(2026, 10, 13, h, tzinfo=UTC) for h in (16, 17, 18)]


def test_backup_on_start(tmp_path):
    clock = FakeClock(datetime(2026, 10, 13, 15, 30, tzinfo=UTC), ticks=1)
    runs = []
    config = _config(tmp_path, backup_on_start=True)
    run_daemon(config, lambda c: runs.append(clock.now()), clock, clock.now)
    assert len(runs) == 2
    assert runs[0] == datetime(2026, 10, 13, 15, 30, tzinfo=UTC)


def test_failure_does_not_stop_daemon_or_extend_health(tmp_path):
    start = datetime(2026, 10, 13, 15, 30, tzinfo=UTC)
    clock = FakeClock(start, ticks=3)
    calls = []

    def failing(_):
        calls.append(1)
        raise RuntimeError("boom")

    config = _config(tmp_path)
    run_daemon(config, failing, clock, clock.now)

    assert len(calls) == 3
    first_deadline = datetime(2026, 10, 13, 16, tzinfo=UTC) + HEALTH_GRACE
    assert is_healthy(config.health_file, first_deadline)
    assert not is_healthy(config.health_file, first_deadline + timedelta(seconds=1))


def test_success_extends_health(tmp_path):
    clock = FakeClock(datetime(2026, 10, 13, 15, 30, tzinfo=UTC), ticks=2)
    config = _config(tmp_path)
    run_daemon(config, lambda c: None, clock, clock.now)
    # last run at 17:00, next at 18:00
    deadline = datetime(2026, 10, 13, 18, tzinfo=UTC) + HEALTH_GRACE
    assert is_healthy(config.health_file, deadline)
    assert not is_healthy(config.health_file, deadline + timedelta(seconds=1))
