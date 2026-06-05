"""Asyncio-baserad scheduler som ersatter cron-i-container.

Triggar samma kodvag som webUI:s 'Kor nu' via Runner.submit, sa alla jobb
gar genom samma flock-lock och SSE-strom. Ingen cron-daemon, ingen /proc/1/
fd/1-pipe-akrobatik, ingen TZ-konfig i imagen som behover synas.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter, CroniterBadCronError

from app import jobs

log = logging.getLogger(__name__)

DEFAULT_SCHEDULE = "0 3 * * *"
DEFAULT_TZ = "Europe/Stockholm"


def _tz():
    name = os.environ.get("TZ", DEFAULT_TZ)
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        log.warning("Okand TZ %r, faller tillbaka pa UTC", name)
        return timezone.utc


class Scheduler:
    """En asyncio-task som vantar tills nasta cron-trigger och submittar jobbet.

    Tystnar 60 sek efter trigger sa samma minut inte triggar tva ganger om
    jobbet ar snabbt.
    """

    def __init__(self, runner, schedule=None):
        self.runner = runner
        self.schedule = schedule or os.environ.get("CRON_SCHEDULE", DEFAULT_SCHEDULE)
        self.tz = _tz()
        self.task: asyncio.Task | None = None
        self.next_run: datetime | None = None
        self.last_run: datetime | None = None
        self._validate()

    def _validate(self):
        try:
            croniter(self.schedule, datetime.now(self.tz))
        except (CroniterBadCronError, ValueError) as exc:
            log.error("Ogiltigt CRON_SCHEDULE %r: %s. Faller tillbaka pa %r.",
                      self.schedule, exc, DEFAULT_SCHEDULE)
            self.schedule = DEFAULT_SCHEDULE

    def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop(), name="kdl-scheduler")
            log.info("Scheduler startad. Schema=%r TZ=%s",
                     self.schedule, self.tz)

    async def stop(self):
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def _loop(self):
        while True:
            now = datetime.now(self.tz)
            it = croniter(self.schedule, now)
            self.next_run = it.get_next(datetime)
            delay = max(0.0, (self.next_run - now).total_seconds())
            log.info("Scheduler: nasta korning %s (om %.0f sek)",
                     self.next_run.strftime("%Y-%m-%d %H:%M:%S %Z"), delay)
            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                break
            log.info("Scheduler: schemalagd korning triggar")
            self.last_run = datetime.now(self.tz)
            ok = self.runner.submit(jobs.run_py_subprocess(
                [], self.runner.broadcaster))
            if not ok:
                log.warning("Scheduler: en korning pagar redan, hoppar over")
            # Undvik att samma minut triggar igen om jobbet var snabbt
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
