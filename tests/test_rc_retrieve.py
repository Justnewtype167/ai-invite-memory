"""R3: lexical retrieval quality and ordering."""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import rc_fixtures

from aiinvite.recall.index import build_index
from aiinvite.recall.retrieve import search


class TestRetrieve(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_rc_hits_"))
        labels = rc_fixtures.qa_labels()
        rc_fixtures.write_store(
            cls.root, [(item["ts"], item["gold"]) for item in labels]
        )
        build_index(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, True)

    def test_gold_in_top_fifty(self) -> None:
        """R3: every gold text is retrieved into its own top-50."""
        for item in rc_fixtures.qa_labels():
            with self.subTest(question=item["question"]):
                hits = search(self.root, item["question"], 50)
                texts = [hit.text for hit in hits]
                self.assertIn(item["gold"], texts)
                self.assertLessEqual(len(hits), 50)
                self.assertLessEqual(len(set(texts)), len(texts))

    def test_scores_are_descending(self) -> None:
        """R3: hits are ordered by descending score with stable ties."""
        hits = search(self.root, "我妈手术是什么时候", 50)
        scores = [hit.score for hit in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_no_match_returns_empty(self) -> None:
        """R3: a query with no matching bigrams returns an empty list."""
        self.assertEqual(search(self.root, "量子纠缠实验"), [])
        self.assertEqual(search(self.root, ""), [])


if __name__ == "__main__":
    unittest.main()
