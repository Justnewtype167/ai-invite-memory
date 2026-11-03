"""M12.1: compiling verifies the hash chain by default."""

from __future__ import annotations

import pathlib
import shutil
import tempfile
import unittest

from aiinvite.capsule import init_store, append_event, seal_store
from aiinvite.errors import E_TAMPER, AiInviteError
from aiinvite.kernel.compiler import compile_kernel
from aiinvite.kernel.errors import E_KN_TAMPER, KernelError
from aiinvite.kernel.kernel import Policy

POLICY = Policy(now="2026-10-29T10:00:00+08:00")
STAMP = "2026-10-29T09:00:00+08:00"


class TestCompileVerifies(unittest.TestCase):
    """A tampered store must not compile into a persona."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_verify_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "mem"
        init_store(self.store)
        append_event(self.store, "user", "今天很累。", STAMP)
        append_event(self.store, "assistant", "听起来很难受。", STAMP)
        seal_store(self.store)
        self.segment = self.store / "evidence" / "seg-0001.jsonl"
        self.original = self.segment.read_bytes()

    def _tamper(self) -> None:
        text = self.original.decode("utf-8").replace("今天很累", "今天很类", 1)
        self.segment.write_bytes(text.encode("utf-8"))

    def test_clean_store_compiles(self) -> None:
        """M12.1: a clean store compiles and the kid is stable."""
        first = compile_kernel(self.store, POLICY, verify=True)
        second = compile_kernel(self.store, POLICY, verify=True)
        self.assertEqual(first.kid, second.kid)

    def test_tampered_store_raises(self) -> None:
        """M12.1: one changed byte stops compilation with E_KN_TAMPER."""
        self._tamper()
        with self.assertRaises(KernelError) as context:
            compile_kernel(self.store, POLICY, verify=True)
        self.assertEqual(context.exception.code, E_KN_TAMPER)
        self.assertIn(E_TAMPER, str(context.exception))

    def test_verify_can_be_disabled(self) -> None:
        """M12.1: verify=False is the explicit fast path, not the default."""
        self._tamper()
        kernel = compile_kernel(self.store, POLICY, verify=False)
        self.assertTrue(kernel.kid)

    def test_underlying_error_is_invite_error(self) -> None:
        """M12.1: the wrapped cause stays inspectable."""
        self._tamper()
        with self.assertRaises(KernelError) as context:
            compile_kernel(self.store, POLICY, verify=True)
        self.assertIsInstance(context.exception.__cause__, AiInviteError)


if __name__ == "__main__":
    unittest.main()