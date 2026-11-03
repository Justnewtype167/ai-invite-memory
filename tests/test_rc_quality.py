"""R7: 4k fidelity against a 32k baseline on 1037 events."""

from __future__ import annotations

import pathlib
import random
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import rc_fixtures

from aiinvite.recall.assemble import assemble
from aiinvite.recall.index import build_index

NOW = "2026-10-29T10:00:00+08:00"


class TestQuality(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_rc_qa_"))
        cls.counts = rc_fixtures.quality_store(cls.root)
        build_index(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, True)

    def _hit(self, budget: int, question: str, gold: str) -> bool:
        context = assemble(self.root, question, budget, NOW)
        return gold in {item.text for item in context.items}

    def test_fidelity(self) -> None:
        """R7: baseline must be 1.0, and 4k fidelity >= 0.90*base and >= 0.85."""
        labels = rc_fixtures.qa_labels()
        normal, neighbor, gold_count = self.counts
        baseline_hits = 0
        small_hits = 0
        for item in labels:
            if self._hit(32768, item["question"], item["gold"]):
                baseline_hits += 1
            if self._hit(4096, item["question"], item["gold"]):
                small_hits += 1
        baseline = baseline_hits / len(labels)
        fidelity = small_hits / len(labels)
        print(
            f"R7 data normal={normal} neighbor={neighbor} gold={gold_count} "
            f"total={normal + neighbor + gold_count}"
        )
        print(
            f"R7 hits 4k={small_hits}/{len(labels)} "
            f"32k={baseline_hits}/{len(labels)} "
            f"baseline={baseline:.4f} fidelity={fidelity:.4f}"
        )
        self.assertEqual(baseline, 1.0, "32k baseline must be 1.0")
        self.assertGreaterEqual(fidelity, 0.90 * baseline)
        self.assertGreaterEqual(fidelity, 0.85)

    def test_budget_pressure(self) -> None:
        """R7: one gold survives 500 same-term distractors within 4k tokens."""
        root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_rc_pressure_"))
        self.addCleanup(shutil.rmtree, root, True)
        gold = "我妈下周三做手术"
        distractors = (
            "手术排到了下午", "病房里又在做手术", "医生说明天有台手术",
            "手术室的灯亮了", "刚做完手术很累", "这台手术做了六个小时",
            "手术费用还没结", "护士推着车去做手术", "手术前不能吃东西",
        )
        rng = random.Random(20261029)
        events: list[tuple[str, str]] = [("2024-01-02T08:00:00Z", gold)]
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        for index in range(500):
            stamp = (start + timedelta(hours=6 * index)).strftime("%Y-%m-%dT%H:%M:%SZ")
            events.append((stamp, distractors[rng.randrange(len(distractors))]))
        rc_fixtures.write_store(root, events)
        build_index(root)
        context = assemble(root, gold, 4096, NOW)
        texts = {item.text for item in context.items}
        print(
            f"R7 pressure events=501 items={len(context.items)} "
            f"total={context.total_tokens} gold={gold in texts}"
        )
        self.assertIn(gold, texts, "gold event must survive budget pressure")
        self.assertLessEqual(context.total_tokens, 4096)


if __name__ == "__main__":
    unittest.main()
