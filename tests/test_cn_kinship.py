"""C1: kinship metrics, source independence, and the kind hard rules."""

from __future__ import annotations

import json
import pathlib
import unittest

from jian_cn.errors import CnError, E_CN_UNKNOWN_TERM
from jian_cn.kinship import Kinship, lexicon_terms, parse_kinship

DATA = pathlib.Path(__file__).resolve().parents[1] / "jian_cn" / "data"
EDGES = frozenset({"F", "M", "H", "W", "OB", "YB", "OS", "YS", "S", "B", "s", "d"})


def _entries(name: str) -> list[dict]:
    payload = json.loads((DATA / name).read_bytes().decode("utf-8"))
    return payload["entries"]


class TestKinshipData(unittest.TestCase):
    def setUp(self) -> None:
        self.lexicon = _entries("kinship.json")
        self.labels = _entries("kinship_labels.json")

    def test_3_5_label_size_and_overlap_is_recorded_only(self) -> None:
        """C1: labels >= 180; overlap with the lexicon is recorded, not a gate (v0.2)."""
        label_terms = {row["term"] for row in self.labels}
        lex_terms = set(lexicon_terms())
        self.assertGreaterEqual(len(label_terms), 180)
        self.overlap = len(label_terms & lex_terms)

    def test_3_5_composites_and_variants(self) -> None:
        """C1: enough 的-composites and spoken/dialect variants."""
        composites = [r for r in self.labels if "的" in r["term"]]
        variants = [r for r in self.labels if r.get("variant") in {"spoken", "dialect"}]
        self.assertGreaterEqual(len(composites), 40)
        self.assertGreaterEqual(len(variants), 14)

    def test_3_6_scoring_set_excludes_lexicon(self) -> None:
        """C1: only terms absent from the lexicon are scored, and they must reach 0.90."""
        lex_terms = set(lexicon_terms())
        scored = [r for r in self.labels if r["term"] not in lex_terms]
        self.assertGreaterEqual(len(scored), 60)
        matched = 0
        misses: list[str] = []
        for row in scored:
            try:
                got = set(parse_kinship(row["term"]).candidates)
            except CnError:
                got = set()
            if got == set(row["candidates"]):
                matched += 1
            else:
                misses.append(row["term"])
        rate = matched / len(scored)
        self.assertGreaterEqual(rate, 0.90, f"misses: {misses}")

    def test_same_source_entries_are_smoke_only(self) -> None:
        """C1: same-source rows are smoke-tested and are not part of the score."""
        lex_terms = set(lexicon_terms())
        same_source = [r for r in self.labels if r["term"] in lex_terms]
        for row in same_source:
            with self.subTest(term=row["term"]):
                self.assertEqual(set(parse_kinship(row["term"]).candidates),
                                 set(row["candidates"]))

    def test_data_integrity(self) -> None:
        """C1: kind, ambiguity and edge names in both data files."""
        for row in self.lexicon:
            self.assertIn(row["kind"], {"kin", "fictive", "social"})
            if row["kind"] != "kin":
                self.assertEqual(row["candidates"], [], row["term"])
            self.assertEqual(row["ambiguous"], len(row["candidates"]) > 1, row["term"])
            for cand in row["candidates"]:
                for edge in cand.split("."):
                    self.assertIn(edge, EDGES, f"{row['term']} -> {cand}")


class TestKinshipParsing(unittest.TestCase):
    def test_composite_is_algorithmic_not_lookup(self) -> None:
        """Constraint 4: composites are parsed, never stored in the lexicon."""
        self.assertNotIn("我爸的哥哥", lexicon_terms())
        result = parse_kinship("我爸的哥哥")
        self.assertEqual(result.candidates, ("F.OB",))
        self.assertEqual(result.kind, "kin")

    def test_three_segment_composite(self) -> None:
        """Each 的-segment contributes edges, then they are concatenated."""
        result = parse_kinship("我爸的弟弟的女儿")
        self.assertEqual(result.candidates, ("F.YB.d",))

    def test_ambiguous_composite_keeps_all_candidates(self) -> None:
        """Ambiguity propagates through the product of candidates."""
        result = parse_kinship("我外甥的儿子")
        self.assertEqual(set(result.candidates), {"OS.s.s", "YS.s.s"})
        self.assertTrue(result.ambiguous)

    def test_fictive_segment_kills_candidates(self) -> None:
        """A fictive segment yields no blood edges at all."""
        result = parse_kinship("我干爹的哥哥")
        self.assertEqual(result.kind, "fictive")
        self.assertEqual(result.candidates, ())

    def test_fictive_and_social_have_no_candidates(self) -> None:
        """Spec 3.2.1: non-kin terms never borrow a blood edge."""
        for term in ("干爹", "干爸", "干妈", "干娘", "干哥", "干姐"):
            with self.subTest(term=term):
                parsed = parse_kinship(term)
                self.assertEqual(parsed.kind, "fictive")
                self.assertEqual(parsed.candidates, ())
        for term in ("师傅", "师父", "老师", "老板"):
            with self.subTest(term=term):
                parsed = parse_kinship(term)
                self.assertEqual(parsed.kind, "social")
                self.assertEqual(parsed.candidates, ())

    def test_adopted_and_step_parents_stay_kin(self) -> None:
        """Spec 3.2.2: step/adoptive parents are kin with a 拟制 note."""
        for term in ("继父", "继母", "养父", "养母"):
            with self.subTest(term=term):
                parsed = parse_kinship(term)
                self.assertEqual(parsed.kind, "kin")
                self.assertTrue(parsed.candidates)

    def test_unknown_term_raises(self) -> None:
        """Spec 3.2: unknown terms raise E_CN_UNKNOWN_TERM instead of guessing."""
        for term in ("远房表舅", "我的表舅", "外星人"):
            with self.subTest(term=term):
                with self.assertRaises(CnError) as ctx:
                    parse_kinship(term)
                self.assertEqual(ctx.exception.code, E_CN_UNKNOWN_TERM)

    def test_result_is_frozen_dataclass(self) -> None:
        """C8: results are dataclasses, not bare dicts."""
        self.assertIsInstance(parse_kinship("堂哥"), Kinship)
        self.assertEqual(parse_kinship("堂哥").to_dict()["candidates"], ["F.OB.s"])


if __name__ == "__main__":
    unittest.main()
