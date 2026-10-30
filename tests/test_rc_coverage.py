"""S4: query-coverage weighting lifts the 20-question top-5 rate to 0.90."""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import rc_fixtures

from jian_recall.index import build_index
from jian_recall.retrieve import search

NOW = "2026-10-29T10:00:00+08:00"
TOP_K = 5


class TestCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_rc_cov_"))
        rc_fixtures.quality_store(cls.root)
        build_index(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, True)

    def test_top5_hit_rate(self) -> None:
        """S4: at least 18 of 20 gold answers appear in the top 5."""
        labels = rc_fixtures.qa_labels()
        hits = 0
        for item in labels:
            found = search(self.root, item["question"], TOP_K, NOW)
            if item["gold"] in {hit.text for hit in found}:
                hits += 1
        rate = hits / len(labels)
        print(f"S4 coverage top5={hits}/{len(labels)} rate={rate:.4f}")
        self.assertGreaterEqual(rate, 0.90)

    def test_scores_descend(self) -> None:
        """S4: hits stay strictly ordered by score."""
        for item in rc_fixtures.qa_labels()[:5]:
            found = search(self.root, item["question"], TOP_K, NOW)
            scores = [hit.score for hit in found]
            self.assertEqual(scores, sorted(scores, reverse=True))
            for score in scores:
                self.assertGreaterEqual(score, 0.0)
                self.assertTrue(score == score)

    def test_full_coverage_beats_partial(self) -> None:
        """S4: the text with every query bigram outranks a partial match."""
        root = pathlib.Path(tempfile.mkdtemp(prefix="jian_rc_cov2_"))
        self.addCleanup(shutil.rmtree, root, True)
        gold = "我妈下周三做手术"
        rc_fixtures.write_store(root, [
            ("2026-06-01T08:00:00Z", gold),
            ("2026-06-01T09:00:00Z", "下周做个小手术"),
        ])
        build_index(root)
        found = search(root, gold, 5, NOW)
        print(f"S4 full-first={[hit.text for hit in found]}")
        self.assertEqual(found[0].text, gold)


if __name__ == "__main__":
    unittest.main()
