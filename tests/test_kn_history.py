"""K4: append-only history, per-entry diff, write-free restore, CLI."""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from jian_kernel import cli
from jian_kernel.errors import E_KN_NO_HISTORY, KernelError
from jian_kernel.history import (
    diff_versions,
    history,
    record_kernel,
    restore,
    verify_kernel,
)
from jian_kernel.kernel import Policy

NOW = "2026-10-29T10:00:00+08:00"


class TestHistory(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_kn_hist_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.policy = Policy(now=NOW)
        events = kn_fixtures.directives(5) + [
            ("2026-01-06T09:00:00Z", "今天天气不错", "turn", None),
        ]
        kn_fixtures.write_store(self.root, events)

    def _record_two(self) -> tuple[bytes, int]:
        first = record_kernel(self.root, self.policy)
        history_path = self.root / "kernel" / "HISTORY.jsonl"
        before = history_path.read_bytes()
        kn_fixtures.append_events(self.root, [
            ("2026-06-01T09:00:00Z", "规则六不许熬夜", "directive", "lock"),
        ])
        second = record_kernel(self.root, self.policy)
        self.assertEqual(second.version, first.version + 1)
        return before, second.version

    def test_history_is_append_only(self) -> None:
        """K4: the second record only appends; old bytes are untouched."""
        before, version = self._record_two()
        entries = history(self.root)
        after = (self.root / "kernel" / "HISTORY.jsonl").read_bytes()
        print(f"K4 history={len(entries)} version={version}")
        self.assertEqual(len(entries), version)
        self.assertTrue(after.startswith(before))
        self.assertEqual(after, before + entries[-1].to_line())
        self.assertEqual([entry.version for entry in entries], [1, 2])

    def test_diff_is_per_entry(self) -> None:
        """K4: diff reports exactly one added entry and no noise."""
        _, _ = self._record_two()
        diff = diff_versions(self.root, 1, 2)
        payload = diff.to_payload()
        print(f"K4 diff added={len(diff.added)} changed={len(diff.changed)} "
              f"removed={len(diff.removed)}")
        self.assertEqual(len(diff.added), 1)
        self.assertEqual(diff.added[0].text, "规则六不许熬夜")
        self.assertEqual(diff.added[0].evidence, ("ev_000007",))
        self.assertEqual(diff.changed, ())
        self.assertEqual(diff.removed, ())
        self.assertEqual(payload["added"][0]["kind"], "directive")

    def test_restore_recompiles_without_writing(self) -> None:
        """K4: restore recomputes the old kid and leaves kernel/ untouched."""
        _, _ = self._record_two()
        entries = history(self.root)
        before = kn_fixtures.snapshot(self.root)
        restored = restore(self.root, 1)
        after = kn_fixtures.snapshot(self.root)
        self.assertEqual(restored.kid, entries[0].kid)
        self.assertEqual(after, before)
        self.assertNotEqual(restored.kid, entries[1].kid)

    def test_missing_version_and_empty_history(self) -> None:
        """K4: absent history and absent versions use E_KN_NO_HISTORY."""
        with self.assertRaises(KernelError) as caught:
            history(self.root)
        self.assertEqual(caught.exception.code, E_KN_NO_HISTORY)
        self._record_two()
        with self.assertRaises(KernelError) as caught:
            restore(self.root, 3)
        self.assertEqual(caught.exception.code, E_KN_NO_HISTORY)
        with self.assertRaises(KernelError) as caught:
            diff_versions(self.root, 1, 3)
        self.assertEqual(caught.exception.code, E_KN_NO_HISTORY)

    def test_verify_and_cli(self) -> None:
        """K4: verify recompiles the latest version; the CLI matches."""
        _, version = self._record_two()
        report = verify_kernel(self.root)
        self.assertEqual(report.version, version)
        self.assertEqual(cli.main(["verify", str(self.root)]), 0)
        self.assertEqual(cli.main(["diff", str(self.root), "--a", "1",
                                   "--b", str(version)]), 0)
        self.assertEqual(cli.main(["history", str(self.root)]), 0)
        self.assertEqual(cli.main(["compile", str(self.root), "--now", NOW]), 0)


if __name__ == "__main__":
    unittest.main()
