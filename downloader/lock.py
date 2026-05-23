"""fcntl-baserad inter-process lock for run.py och webUI.

Hindrar parallella nedladdnings-/postproc-korningar mellan cron och webUI -
de skulle annars tampas om samma arkivfiler och temp-mappar.

Hold-pattern: behall fd oppen sa lange du "ager" lasen; flock slappes
automatiskt nar fd stangs (vid release() eller processavslut).
"""
import errno
import fcntl
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_LOCK_PATH = os.environ.get("RUN_LOCK_PATH", "/state/run.lock")


class Lock:
    """Exklusiv flock pa en fil. Non-blocking acquire."""

    def __init__(self, path=None):
        self.path = Path(path or DEFAULT_LOCK_PATH)
        self._fd: int | None = None

    def acquire(self) -> bool:
        """Returnerar True om lasningen lyckades, False om annan ar har den."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EWOULDBLOCK, errno.EACCES):
                return False
            raise
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        self._fd = fd
        return True

    def release(self):
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def __enter__(self):
        if not self.acquire():
            raise BlockingIOError(f"Lock redan haldet: {self.path}")
        return self

    def __exit__(self, *exc):
        self.release()


def is_held(path=None) -> bool:
    """Non-blocking check: returnerar True om nagon haller flock pa filen."""
    p = Path(path or DEFAULT_LOCK_PATH)
    if not p.exists():
        return False
    try:
        fd = os.open(p, os.O_RDWR)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
