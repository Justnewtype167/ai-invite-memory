"""S3: text-level dedupe across slots, with merged ids and stable order."""

from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import rc_fixtures

from aiinvite.recall.assemble import assemble
from aiinvite.recall.index import build_index

NOW = "2026-10-29T10:00:00+08:00"
RANK = {"trigger": 0, "retrieved": 1, "recent": 2}


def _events() -> list[tuple[str, str]]:
    text = "每年今天我们都去看海"
    rows = [
        ("2023-10-29T10:00:00Z", text),
        ("2024-10-29T10:00:00Z", text),
        ("2019-01-01T10:00:00Z", text),
        ("2025-06-01T08:00:00Z", text),
    ]
    for index in range(7):
        rows.append((f"2025-06-01T09:0{index}:00Z", f"普通日常{index + 1}"))
    return rows


class TestDedupe(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_rc_dedupe_"))
        rc_fixtures.write_store(cls.root, _events())
        build_index(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.root, True)

    def test_cross_slot_keeps_trigger_and_records_merged(self) -> None:
        """S3: one text in three slots survives once, as a trigger hit."""
        context = assemble(self.root, "看海", 4096, NOW)
        text = "每年今天我们都去看海"
        matches = [item for item in context.items if item.text == text]
        print(
            f"S3 cross-slot items={len(matches)} "
            f"slot={matches[0].slot if matches else None} "
            f"merged={matches[0].merged if matches else None}"
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].slot, "trigger")
        self.assertEqual(
            matches[0].merged,
            ("ev_000001", "ev_000003", "ev_000004"),
        )
        texts = [item.text for item in context.items]
        self.assertEqual(len(texts), len(set(texts)))
        ranks = [RANK[item.slot] for item in context.items]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(
            context.total_tokens, sum(item.tokens for item in context.items)
        )

    def test_recent_duplicates_collapse_once(self) -> None:
        """S3: three identical recent texts become one item with two merged ids."""
        root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_rc_recent_"))
        self.addCleanup(shutil.rmtree, root, True)
        rows: list[tuple[str, str]] = [
            (f"2025-06-01T08:0{index}:00Z", "一样的日常") for index in range(3)
        ]
        for index in range(5):
            rows.append((f"2025-06-01T09:0{index}:00Z", f"不同的日常{index + 1}"))
        rc_fixtures.write_store(root, rows)
        build_index(root)
        context = assemble(root, "完全不存在的词", 4096, NOW)
        dupes = [item for item in context.items if item.text == "一样的日常"]
        print(
            f"S3 recent dupes={len(dupes)} merged={dupes[0].merged if dupes else None} "
            f"items={len(context.items)}"
        )
        self.assertEqual(len(dupes), 1)
        self.assertEqual(dupes[0].slot, "recent")
        self.assertEqual(dupes[0].merged, ("ev_000001", "ev_000002"))
        self.assertEqual(len(context.items), 6)


if __name__ == "__main__":
    unittest.main()
