"""K1: compilation is deterministic and every entry is sourced."""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from aiinvite.kernel.compiler import compile_kernel
from aiinvite.kernel.kernel import EvidenceEvent, Policy

NOW = "2026-10-29T10:00:00+08:00"
RUNS = 100


class TestCompile(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_kn_compile_"))
        cls.addClassCleanup(shutil.rmtree, cls.root, True)
        cls.events = [
            ("2026-01-01T09:00:00Z", "今天天气不错", "turn", None),
            ("2026-01-02T09:00:00Z", "以后不许半夜打电话", "directive", "lock"),
            ("2026-01-03T09:00:00Z", "妈妈下周三做手术", "turn", None),
            ("2026-01-04T09:00:00Z", "我答应你下次一定早点睡", "turn", None),
            ("2026-01-05T09:00:00Z", "已完成那个事", "turn", None),
        ]
        kn_fixtures.write_store(cls.root, cls.events)

    def test_hundred_compiles_are_byte_identical(self) -> None:
        """K1: 100 compiles of one store produce identical bytes."""
        policy = Policy(now=NOW)
        first = compile_kernel(self.root, policy)
        first_files = first.files(1)
        identical = 1
        for _ in range(RUNS - 1):
            again = compile_kernel(self.root, policy)
            if again.kid == first.kid and again.files(1) == first_files:
                identical += 1
        print(f"K1 identical={identical}/{RUNS} kid={first.kid[:12]}")
        self.assertEqual(identical, RUNS)

    def test_every_entry_is_sourced(self) -> None:
        """K1: every canon, edge and anchor cites an existing event."""
        kernel = compile_kernel(self.root, Policy(now=NOW))
        known = self._ids()
        for entry in kernel.canon:
            self.assertTrue(entry.evidence)
            self.assertTrue(set(entry.evidence) <= known)
        for edge in kernel.edges:
            self.assertIn(edge.event_id, known)
        for anchor in kernel.anchors:
            self.assertIn(anchor.event_id, known)

    def _ids(self) -> set[str]:
        from aiinvite.kernel.compiler import read_evidence

        return {event.event_id for event in read_evidence(self.root)}

    def test_canon_rules(self) -> None:
        """K1: one lock directive, and the promise is cancelled by 已完成."""
        kernel = compile_kernel(self.root, Policy(now=NOW))
        kinds = [entry.kind for entry in kernel.canon]
        print(f"K1 canon={len(kernel.canon)} kinds={kinds}")
        self.assertEqual(kinds, ["directive"])
        self.assertEqual(kernel.canon[0].text, "以后不许半夜打电话")
        self.assertIn("已完成", self.events[-1][1])

    def test_graph_and_self(self) -> None:
        """K1: kinship edges, time anchors and the self template are filled."""
        kernel = compile_kernel(self.root, Policy(now=NOW))
        self.assertIn("妈妈", {edge.term for edge in kernel.edges})
        self.assertTrue(kernel.anchors)
        self.assertIn("下周", {anchor.expr for anchor in kernel.anchors})
        self.assertIn("- events: 5", kernel.self_md)
        self.assertIn("- known_days:", kernel.self_md)

    def test_promise_without_cancel_is_kept(self) -> None:
        """K1: an uncancelled promise becomes a canon entry."""
        root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_kn_promise_"))
        self.addCleanup(shutil.rmtree, root, True)
        kn_fixtures.write_store(root, [
            ("2026-01-01T09:00:00Z", "今天天气不错", "turn", None),
            ("2026-01-02T09:00:00Z", "我答应你下次一定早点睡", "turn", None),
        ])
        kernel = compile_kernel(root, Policy(now=NOW))
        self.assertEqual([entry.kind for entry in kernel.canon], ["promise"])
        self.assertEqual(kernel.canon[0].evidence, ("ev_000002",))

    def test_typed_evidence_is_read(self) -> None:
        """K1: the reader normalizes stamps and keeps type/kind."""
        from aiinvite.kernel.compiler import read_evidence

        events = read_evidence(self.root)
        self.assertIsInstance(events[0], EvidenceEvent)
        self.assertEqual(events[1].type, "directive")
        self.assertEqual(events[1].kind, "lock")


if __name__ == "__main__":
    unittest.main()
