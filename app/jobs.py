"""Korning av jobb fran webUI: SSE-broadcast + lock + subprocess.

En Broadcaster med tail-historik ger nya SSE-klienter de senaste raderna sa
man inte missar starten av ett jobb om man oppnar fliken efter att man startat.
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
        # Spela upp historik forst sa en ny klient ser pagaende kornings logg.
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
    """Triggar run.py som asyncio-subprocess och strommar logg via broadcaster.

    Hindrar parallella webUI-utlosta korningar via intern task-handle. Skyddet
    galler an sa lange BARA mot webUI-parallellism; cron kan annu starta jobb
    parallellt med ett manuellt - en flock-baserad inter-process lock kommer
    senare.
    """

    def __init__(self, broadcaster: Broadcaster):
        self.broadcaster = broadcaster
        self.task: asyncio.Task | None = None

    def is_running(self) -> bool:
        return self.task is not None and not self.task.done()

    async def start(self, args: list[str] | None = None) -> bool:
        if self.is_running():
            return False
        self.task = asyncio.create_task(self._run(args or []))
        return True

    async def _run(self, args: list[str]):
        await self.broadcaster.publish({"event": "start", "args": args})
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "run.py",
                "--config", settings.config_path, *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(PROJECT_ROOT),
            )
            assert proc.stdout is not None
            async for raw in proc.stdout:
                await self.broadcaster.publish(
                    {"event": "log", "line": raw.decode("utf-8", "replace").rstrip()}
                )
            code = await proc.wait()
        except Exception as exc:
            log.exception("Jobb-runner kraschade")
            await self.broadcaster.publish({"event": "error", "message": str(exc)})
            return
        await self.broadcaster.publish({"event": "end", "code": code})
