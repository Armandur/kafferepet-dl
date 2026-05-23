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
    """Kor en async-uppgift i taget. Hindrar parallella webUI-utlosta jobb.

    OBS: skyddet galler an sa lange BARA webUI-intern parallellism. En cron-
    korning som startas av cron-daemonen kan annu kollidera; flock-baserad
    inter-process lock kommer i en senare commit.
    """

    def __init__(self, broadcaster: Broadcaster):
        self.broadcaster = broadcaster
        self.task: asyncio.Task | None = None

    def is_running(self) -> bool:
        return self.task is not None and not self.task.done()

    def submit(self, coro) -> bool:
        if self.is_running():
            return False
        self.task = asyncio.create_task(coro)
        return True


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
