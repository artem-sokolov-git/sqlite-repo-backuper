import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from croniter import croniter

from .config import Config
from .health import write_deadline

log = logging.getLogger(__name__)

HEALTH_GRACE = timedelta(hours=1)


class Stop(Protocol):
    def is_set(self) -> bool: ...
    def wait(self, timeout: float) -> bool: ...


def next_run(schedule: str, after: datetime) -> datetime:
    return croniter(schedule, after).get_next(datetime)


def run_daemon(
    config: Config,
    job: Callable[[Config], None],
    stop: Stop,
    now: Callable[[], datetime] | None = None,
) -> None:
    """Run `job` on the cron schedule until `stop` is set.

    A failing job is logged and retried on the next tick. The health file is only moved
    forward after a success, so repeated failures turn the container unhealthy.
    """
    now = now or (lambda: datetime.now(config.timezone))

    def execute() -> bool:
        try:
            job(config)
        except Exception:
            log.exception("backup failed")
            return False
        return True

    upcoming = next_run(config.schedule, now())
    write_deadline(config.health_file, upcoming + HEALTH_GRACE)
    log.info("next backup at %s", upcoming.isoformat(timespec="seconds"))

    if config.backup_on_start:
        execute()

    while not stop.is_set():
        if stop.wait(max(0.0, (upcoming - now()).total_seconds())):
            break
        ok = execute()
        upcoming = next_run(config.schedule, now())
        if ok:
            write_deadline(config.health_file, upcoming + HEALTH_GRACE)
        log.info("next backup at %s", upcoming.isoformat(timespec="seconds"))
