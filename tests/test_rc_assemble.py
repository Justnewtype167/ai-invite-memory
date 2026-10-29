"""R4: budget caps, determinism and discard order."""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import rc_fixtures

from jian_recall.assemble import assemble
from jian_recall.errors import E_RC_BAD_BUDGET, RecallError
from jian_recall.index import build_index
from jian_recall.retrieve import search

NOW = "2026-10-29T10:00:00+08:00"
QUERY = "项目进度"


class TestAssemble(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_rc_asm_"))
        events: list[tuple[str, str]] = []
        for index in range(60):
            events.append(
                (f"2024-01-01T00:{index:02d}:00Z", "项目进度又更新了一次")
            )
        events.append(("2021-10-29T10:00:00Z", "纪念日回忆"))
        events.append(("2022-10-29T10:00:00Z", "纪念日回忆二"))
        events.append(("2023-10-29T10:00:00Z", "纪念日回忆三"))
        for index in range(8):
            events.append((f"2025-06-01T08:0{index}:00Z", "最近的日常记录"))
        rc_fixtures.write_store(cls.root, events)
        build_index(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, True)

    def test_caps_and_total(self) -> None:
        """R4.1-2: total within budget and every slot within its cap."""
        budget = 512
        context = assemble(self.root, QUERY, budget, NOW)
        self.assertLessEqual(context.total_tokens, budget)
        usage = {"recent": 0, "trigger": 0, "retrieved": 0}
        for item in context.items:
            usage[item.slot] += item.tokens
        self.assertLessEqual(usage["recent"], budget * 25 // 100)
        self.assertLessEqual(usage["trigger"], budget * 10 // 100)
        self.assertLessEqual(
            usage["retrieved"], budget - budget * 25 // 100 - budget * 10 // 100
        )
        self.assertEqual(context.total_tokens, sum(item.tokens for item in context.items))

    def test_discard_order(self) -> None:
        """R4.5: retrieved tail is dropped while trigger and recent survive."""
        retrieved = search(self.root, QUERY, 50, NOW)
        self.assertGreater(len(retrieved), 20)
        context = assemble(self.root, QUERY, 512, NOW)
        slots = [item.slot for item in context.items]
        self.assertEqual(slots[:3], ["trigger"] * 3)
        self.assertEqual(slots[-8:], ["recent"] * 8)
        kept = [item for item in context.items if item.slot == "retrieved"]
        self.assertGreater(len(kept), 0)
        self.assertLess(len(kept), len(retrieved))
        self.assertEqual(slots, ["trigger"] * 3 + ["retrieved"] * len(kept)
                         + ["recent"] * 8)

    def test_small_budget_keeps_protected_slots(self) -> None:
        """R4: a 256-token budget keeps trigger hits and recent events."""
        context = assemble(self.root, QUERY, 256, NOW)
        self.assertLessEqual(context.total_tokens, 256)
        usage = {"recent": 0, "trigger": 0, "retrieved": 0}
        for item in context.items:
            usage[item.slot] += item.tokens
        self.assertLessEqual(usage["recent"], 64)
        self.assertLessEqual(usage["trigger"], 25)
        self.assertGreater(usage["trigger"], 0)
        self.assertGreater(usage["recent"], 0)

    def test_scarce_store_is_not_padded(self) -> None:
        """R4.3: a store with few candidates stays below the budget."""
        small = pathlib.Path(tempfile.mkdtemp(prefix="jian_rc_small_"))
        self.addCleanup(shutil.rmtree, small, True)
        rc_fixtures.write_store(small, [("2024-01-01T10:00:00Z", "只有两条记忆")])
        build_index(small)
        context = assemble(small, "完全不存在的词", 4096, NOW)
        self.assertLess(context.total_tokens, 4096)
        self.assertEqual(len(context.items), 1)

    def test_byte_identical_twice(self) -> None:
        """R4.4: the same inputs produce byte-identical output."""
        first = assemble(self.root, QUERY, 512, NOW)
        second = assemble(self.root, QUERY, 512, NOW)
        self.assertEqual(first.to_json(), second.to_json())

    def test_budget_bounds(self) -> None:
        """R4: budgets outside 256-200000 raise E_RC_BAD_BUDGET."""
        for budget in (255, 200001, 0):
            with self.subTest(budget=budget):
                with self.assertRaises(RecallError) as error:
                    assemble(self.root, QUERY, budget, NOW)
                self.assertEqual(error.exception.code, E_RC_BAD_BUDGET)


if __name__ == "__main__":
    unittest.main()
