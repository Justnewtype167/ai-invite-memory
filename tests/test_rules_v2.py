"""V1: rules_v2.json is the single scoring source for the six v2 rules."""

from __future__ import annotations

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from jian_pcs.probes import (
    RULE_IDS,
    RULES_PATH,
    V2_OPERATORS,
    load_all_probes,
    load_rules_v2,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCORED_FIELDS = {"id", "text", "op", "args", "human"}


class TestRulesV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rules = load_rules_v2()
        cls.probes = load_all_probes()

    def test_six_rules_in_order(self) -> None:
        """V1: exactly six scored rules, ids R1-R6 in order."""
        ids = tuple(rule.rule_id for rule in self.rules)
        print(f"V1 rules={ids}")
        self.assertEqual(ids, RULE_IDS)
        self.assertEqual(len(self.rules), 6)

    def test_operator_whitelist_and_args(self) -> None:
        """V1: every op is in the v2 whitelist and its args are well-formed."""
        for rule in self.rules:
            self.assertIn(rule.op, V2_OPERATORS)
            if rule.op == "none_of":
                self.assertTrue(rule.words)
                self.assertEqual(rule.sentences, None)
            elif rule.op == "max_sentences_and_questions":
                self.assertEqual(rule.sentences, 2)
                self.assertEqual(rule.questions, 1)
            elif rule.op == "max_chars":
                self.assertEqual(rule.chars, 40)
            else:
                self.assertIsNone(rule.words or None)
        print(
            "V1 ops="
            + ", ".join(f"{rule.rule_id}:{rule.op}" for rule in self.rules)
        )

    def test_every_rule_has_a_human_definition(self) -> None:
        """V1: the executable definition an annotator reads is never empty."""
        empty = [rule.rule_id for rule in self.rules if not rule.human.strip()]
        print(f"V1 human empty={empty}")
        self.assertEqual(empty, [])
        for rule in self.rules:
            self.assertNotIn("判定", rule.text, "text is the short sentence")

    def test_probes_do_not_repeat_rule_limits(self) -> None:
        """V1: probes only echo the op; limits come from the rule file alone."""
        bad = []
        for probe in self.probes:
            rule = next(item for item in self.rules if item.rule_id == probe.rule)
            expect = probe.expect
            if expect.op != rule.op:
                bad.append((probe.probe_id, "op"))
            if expect.words != rule.words and rule.op == "none_of":
                bad.append((probe.probe_id, "words"))
            if rule.op == "max_sentences_and_questions" and (
                expect.sentences != rule.sentences
                or expect.questions != rule.questions
            ):
                bad.append((probe.probe_id, "limits"))
            if rule.op == "max_chars" and expect.chars != rule.chars:
                bad.append((probe.probe_id, "chars"))
            if rule.op == "shares_two_chars_with_source":
                if not expect.echo_source.strip():
                    bad.append((probe.probe_id, "echo-source"))
            elif expect.echo_source:
                bad.append((probe.probe_id, "extra-echo-source"))
            if expect.must_contain_any:
                bad.append((probe.probe_id, "legacy-candidates"))
        print(f"V1 echoed-limit violations={bad}")
        self.assertEqual(bad, [])

    def test_non_scored_is_not_counted(self) -> None:
        """V1: the semantic rule is kept as prose but excluded from scoring."""
        payload = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        raw = payload["rules"]
        self.assertEqual([item["id"] for item in raw], list(RULE_IDS))
        for item in raw:
            self.assertEqual(set(item), SCORED_FIELDS)
        non_scored = payload.get("non_scored", [])
        print(f"V1 non_scored={len(non_scored)} scored={len(raw)}")
        self.assertTrue(non_scored)
        for item in non_scored:
            self.assertNotIn("id", item)
            self.assertNotIn("op", item)
        known = {rule.rule_id for rule in self.rules}
        self.assertEqual(len(known), 6)

    def test_no_self_md_requirement(self) -> None:
        """V1: scoring never depends on self.md containing the rules."""
        self.assertTrue(RULES_PATH.exists())
        self.assertEqual(
            ROOT / "jian_pcs" / "data" / "rules_v2.json",
            RULES_PATH,
        )
        references = [
            path.name
            for path in (ROOT / "jian_pcs").glob("*.py")
            if "self.md" in path.read_text(encoding="utf-8")
        ]
        print(f"V1 self.md references={references}")
        self.assertEqual(references, [])
        operators = {probe.expect.op for probe in self.probes}
        print(f"V1 probe operators={sorted(operators)}")
        self.assertTrue(operators <= set(V2_OPERATORS))


if __name__ == "__main__":
    unittest.main()
