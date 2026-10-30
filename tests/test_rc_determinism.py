"""S5: dedupe and coverage keep every output byte-identical across runs."""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import rc_fixtures

from jian_recall.assemble import assemble
from jian_recall.index import build_index
from jian_recall.retrieve import search

NOW = "2026-10-29T10:00:00+08:00"
QUERY = "我妈下周三做手术"


class TestDeterminism(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_rc_det_"))
        rows: list[tuple[str, str]] = []
        for index in range(40):
            text = "重复的同一句话" if index % 4 == 0 else f"记忆片段{index + 1}"
            rows.append((f"2025-01-01T00:{index:02d}:00Z", text))
        rows.append(("2026-10-28T10:00:00Z", QUERY))
        rc_fixtures.write_store(cls.root, rows)
        build_index(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, True)

    def test_assemble_is_byte_identical(self) -> None:
        """S5: three assemblies serialize to the same bytes."""
        runs = [assemble(self.root, QUERY, 4096, NOW).to_json() for _ in range(3)]
        print(f"S5 assemble identical={len(set(runs)) == 1} bytes={len(runs[0])}")
        self.assertEqual(len(set(runs)), 1)

    def test_search_is_stable(self) -> None:
        """S5: repeated searches return the same ids, texts and scores."""
        runs = [
            tuple((hit.event_id, hit.text, hit.score)
                  for hit in search(self.root, QUERY, 20, NOW))
            for _ in range(3)
        ]
        self.assertEqual(len(set(runs)), 1)

    def test_merged_is_stable(self) -> None:
        """S5: merged id tuples are identical across runs."""
        merged = [
            tuple(
                (item.event_id, item.merged)
                for item in assemble(self.root, QUERY, 4096, NOW).items
            )
            for _ in range(3)
        ]
        self.assertEqual(len(set(merged)), 1)


if __name__ == "__main__":
    unittest.main()
