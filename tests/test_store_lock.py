"""L1-L6: one writer per store, enforced across processes."""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.errors import ALL_CODES, E_LOCK, AiInviteError
from aiinvite.serve import MemoryService
from aiinvite.serve.locks import LOCK_DIR, LOCK_SUFFIX, StoreLock

NOW = "2026-11-01T12:00:00+08:00"
CHILD = (
    "import sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from aiinvite.serve.locks import StoreLock\n"
    "lock = StoreLock(sys.argv[2])\n"
    "lock.acquire()\n"
    "print('held', flush=True)\n"
    "sys.stdin.read(1)\n"
    "lock.release()\n"
)


class TestStoreLock(unittest.TestCase):
    """The lock itself: exclusive, advisory, released on demand."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="lock_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.path = self.root / "u1.lock"

    def test_l1_second_holder_in_one_process_is_refused(self) -> None:
        """L1: two file handles, one lock -- the second one fails fast."""
        first = StoreLock(self.path)
        first.acquire()
        self.addCleanup(first.release)
        self.assertTrue(first.held)
        second = StoreLock(self.path)
        with self.assertRaises(AiInviteError) as caught:
            second.acquire()
        self.assertEqual(caught.exception.code, E_LOCK)
        first.release()
        second.acquire()
        second.release()

    def test_l2_release_is_idempotent(self) -> None:
        """L2: releasing twice must not close a descriptor twice."""
        lock = StoreLock(self.path)
        lock.acquire()
        lock.release()
        lock.release()
        self.assertFalse(lock.held)

    def test_l3_another_process_cannot_take_it(self) -> None:
        """L3: the guarantee that matters -- a real second process."""
        child = subprocess.Popen(
            [sys.executable, "-c", CHILD, str(ROOT), str(self.path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(child.kill)
        self.assertEqual(child.stdout.readline().strip(), "held")
        with self.assertRaises(AiInviteError) as caught:
            StoreLock(self.path).acquire()
        self.assertEqual(caught.exception.code, E_LOCK)
        child.stdin.write("x")
        child.stdin.flush()
        child.wait(timeout=30)
        lock = StoreLock(self.path)
        lock.acquire()
        lock.release()

    def test_l4_lock_file_is_outside_the_store(self) -> None:
        """L4: a store directory carries evidence only; seal/export reject extras."""
        service = MemoryService(self.root / "users", "qwen3.5:9b", now=NOW)
        self.addCleanup(service.close)
        service.turn("u1", "我叫老周")
        store = service.store_for("u1")
        self.assertFalse((store / LOCK_DIR).exists())
        self.assertTrue((self.root / "users" / LOCK_DIR / ("u1" + LOCK_SUFFIX)).is_file())
        self.assertEqual([p.name for p in store.iterdir() if p.is_file()], ["chain.json"])

    def test_l5_two_services_can_serve_one_key(self) -> None:
        """L5: the lock is per operation, so a second instance may read too."""
        root = self.root / "users"
        first = MemoryService(root, "qwen3.5:9b", now=NOW)
        self.addCleanup(first.close)
        first.turn("u1", "我叫老周")
        second = MemoryService(root, "qwen3.5:9b", now=NOW)
        self.addCleanup(second.close)
        self.assertEqual(second.view("u1")["card"]["address"]["call"], "老周")

    def test_l6_the_code_is_part_of_the_contract(self) -> None:
        """L6: a backend maps E_LOCK to a retry, so the code must be declared."""
        self.assertIn(E_LOCK, ALL_CODES)


if __name__ == "__main__":
    unittest.main()
