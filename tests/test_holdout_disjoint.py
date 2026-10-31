"""W3: the frozen holdout shares no (source, probe_id) key with the tuning set."""

from __future__ import annotations

import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOLDOUT_KEY = ROOT / "human_eval" / "holdout_key.json"
TUNING_KEY = ROOT / "human_eval" / "key_v2.json"
EXPECTED_ROWS = 60
BASE_IDS = {f"p{index:02d}" for index in range(1, 31)}


def _load(path: pathlib.Path) -> dict[str, dict[str, object]]:
    return json.loads(path.read_text(encoding="utf-8"))


class TestHoldoutDisjoint(unittest.TestCase):
    def test_holdout_is_disjoint_and_complete(self) -> None:
        """W3: 60 rows, two s2 sources, zero overlap with the tuning key."""
        holdout = _load(HOLDOUT_KEY)
        tuning = _load(TUNING_KEY)
        holdout_keys = {
            (str(item["source"]), str(item["probe_id"]))
            for item in holdout.values()
        }
        tuning_keys = {
            (str(item["source"]), str(item["probe_id"]))
            for item in tuning.values()
        }
        sources = {str(item["source"]) for item in holdout.values()}
        print(
            f"W3 holdout={len(holdout)} tuning={len(tuning)} "
            f"overlap={len(holdout_keys & tuning_keys)} sources={sorted(sources)}"
        )
        self.assertEqual(len(holdout), EXPECTED_ROWS)
        self.assertEqual(len(holdout_keys), EXPECTED_ROWS)
        self.assertEqual(len(tuning), EXPECTED_ROWS)
        self.assertEqual(holdout_keys & tuning_keys, set())
        self.assertEqual(sources, {"qwen_s2", "glm_s2"})
        for source in ("qwen_s2", "glm_s2"):
            ids = {
                str(item["probe_id"])
                for item in holdout.values()
                if str(item["source"]) == source
            }
            self.assertEqual(ids, BASE_IDS)


if __name__ == "__main__":
    unittest.main()
