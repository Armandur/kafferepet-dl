"""Jobbkorning: SSE-broadcast + en koordinator som korar en uppgift i taget.

Runner accepterar valfri coroutine (inte bara subprocess), sa run.py-jobb och
importflodena delar samma "kor-en-i-taget"-skydd och samma logg-strom.
"""
import asyncio
import logging
import sys
from collections import deque

from app.config import PROJECT_ROOT, settings

log = logging.getLogger(__name__)


class Broadcaster:
    """Asyncio pub/sub med rullande historikbuffer."""

    def __init__(self, history_size=500):
        self.subscribers: set[asyncio.Queue] = set()
        self.history: deque = deque(maxlen=history_size)

    async def subscribe(self):
        q: asyncio.Queue = asyncio.Queue()
        for msg in list(self.history):
            await q.put(msg)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q):
        self.subscribers.discard(q)

    async def publish(self, msg):
        self.history.append(msg)
        for q in list(self.subscribers):
            await q.put(msg)


class Runner:
    """Kör en async-uppgift i taget via en FIFO-kö.

    Runner accepterar valfri coroutine. En worker-loop betar av kön sekventiellt
    för att undvika kollisioner i flock-lås och sleep_requests.
    """

    def __init__(self, broadcaster: Broadcaster):
        self.broadcaster = broadcaster
        self.queue: deque = deque()
        self.worker_task: asyncio.Task | None = None
        self.current_task: asyncio.Task | None = None

    def is_running(self) -> bool:
        """Returnerar True om ett jobb bearbetas just nu."""
        return self.current_task is not None and not self.current_task.done()

    def get_queued_count(self) -> int:
        """Antal jobb som väntar i kön (exklusive det som körs)."""
        return len(self.queue)

    def submit(self, coro) -> int:
        """Lägger till ett jobb i kön och startar workern om den sover."""
        self.queue.append(coro)
        queued = len(self.queue)
        if self.worker_task is None or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._worker())

        # Publicera kö-status (lite fördröjt så workern hinner starta)
        asyncio.create_task(self._broadcast_queue())
        return queued

    async def _broadcast_queue(self):
        await self.broadcaster.publish({
            "event": "queue",
            "pending": self.get_queued_count(),
            "running": self.is_running()
        })

    async def _worker(self):
        while self.queue:
            coro = self.queue.popleft()
            await self._broadcast_queue()

            self.current_task = asyncio.create_task(coro)
            try:
                await self.current_task
            except Exception as exc:
                log.exception("Jobb kraschade i worker")
                await self.broadcaster.publish({"event": "error", "message": str(exc)})
                # Se till att 'end' når fram om coroutinen dog tidigt
                await self.broadcaster.publish({"event": "end", "code": 1})
            finally:
                self.current_task = None

            await self._broadcast_queue()


async def _stream_subprocess(proc, broadcaster, prefix=""):
    """Stromma stdout-rader fran en asyncio-subprocess till broadcaster."""
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip()
        await broadcaster.publish({"event": "log", "line": f"{prefix}{line}"})
    return await proc.wait()


async def run_py_subprocess(args: list[str], broadcaster: Broadcaster):
    """Coroutine som triggar `python run.py ...` och stromrar dess logg."""
    await broadcaster.publish({"event": "start", "args": args})
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "run.py",
            "--config", settings.config_path, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(PROJECT_ROOT),
        )
        code = await _stream_subprocess(proc, broadcaster)
    except Exception as exc:
        log.exception("run_py_subprocess kraschade")
        await broadcaster.publish({"event": "error", "message": str(exc)})
        return
    await broadcaster.publish({"event": "end", "code": code})
