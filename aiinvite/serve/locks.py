"""One writer per store, enforced across processes (M38).

The per-key threading lock in ``MemoryService`` serialises turns inside one
process. It cannot stop an operator from starting a second instance over the
same data directory -- a restart that overlapped the old one, two workers
behind one load balancer, a cron job that imports the same root. Two writers
over one hash chain is not a performance problem: the second one chains an
event onto a head the other never saw, and the store fails verification from
then on.

So each open store takes an exclusive advisory lock on a file outside the
store directory:

* POSIX: ``fcntl.flock`` with ``LOCK_NB``;
* Windows: ``msvcrt.locking`` with ``LK_NBLCK``.

The lock file lives in ``<root>/.locks/<key>.lock``, not inside
``<root>/<key>/``: a store directory is content-addressed evidence, and seal /
export / snapshot reject a directory that carries files they do not expect.

The lock is advisory: it protects a store from another process that uses this
module, not from an editor that rewrites the files. That is the same boundary
the hash chain draws -- it can prove tampering, not prevent it.
"""
from __future__ import annotations

import os
import pathlib

from aiinvite.errors import E_LOCK, AiInviteError

LOCK_DIR = ".locks"
LOCK_SUFFIX = ".lock"


def _lock(fd: int) -> None:
    """Take a non-blocking exclusive lock on fd, or raise OSError."""
    if os.name == "nt":  # pragma: no cover - exercised on Windows
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd: int) -> None:
    """Release the lock taken by :func:`_lock`."""
    if os.name == "nt":  # pragma: no cover - exercised on Windows
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_UN)


class StoreLock:
    """An exclusive lock on one store, held while a session is warm."""

    def __init__(self, path):
        """Remember where the lock file goes; nothing is opened yet."""
        self.path = pathlib.Path(path)
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        """Return whether this object currently holds the lock."""
        return self._fd is not None

    def acquire(self):
        """Take the lock or raise ``E_LOCK`` when another process holds it."""
        if self._fd is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            _lock(fd)
        except OSError as error:
            os.close(fd)
            raise AiInviteError(
                E_LOCK, f"另一个进程正在写这个 store：{self.path.parent.parent.name}"
            ) from error
        self._fd = fd

    def release(self) -> None:
        """Release the lock; safe to call twice."""
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            _unlock(fd)
        finally:
            os.close(fd)
