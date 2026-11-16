"""S1-S8: the user's standing rules reach the prompt, and only the rules do."""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.capsule import append_event, init_store
from aiinvite.host import HostSession
from aiinvite.persona.standing import (
    MAX_ITEM,
    STANDING_HEADER,
    render_standing,
    standing_rules,
)
from aiinvite.recall.tokenizer import estimate_tokens
from aiinvite.serve import MemoryService

STAMP = "2026-11-01T09:00:00+08:00"
NOW = "2026-11-01T12:00:00+08:00"


def entry(kind: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(kind=kind, text=text)


class TestStandingRules(unittest.TestCase):
    """The renderer itself: what counts as a rule and how much of it is shown."""

    def test_s1_only_directives_are_rules(self) -> None:
        """S1: a promise and a proposal are not instructions for the next reply."""
        rules = standing_rules([
            entry("promise", "我答应你明天早睡"),
            entry("directive", "回复控制在两句以内"),
            entry("trait", "温柔一点"),
        ])
        self.assertEqual(rules, ("回复控制在两句以内",))

    def test_s2_duplicates_collapse(self) -> None:
        """S2: the same rule written twice is shown once."""
        rules = standing_rules([
            entry("directive", "别叫我宝贝"),
            entry("directive", "别叫我宝贝"),
        ])
        self.assertEqual(rules, ("别叫我宝贝",))

    def test_s3_over_budget_keeps_the_newest(self) -> None:
        """S3: the canonical order is chronological, so the newest rules win."""
        entries = [entry("directive", f"第{index}条规则：" + "字" * 40) for index in range(10)]
        rules = standing_rules(entries, budget=120)
        self.assertTrue(rules)
        self.assertIn("第9条规则", rules[-1])
        self.assertNotIn("第0条规则", rules)

    def test_s4_a_rule_is_one_clean_line(self) -> None:
        """S4: newlines and control characters cannot break the prompt layout."""
        rules = standing_rules([entry("directive", "  回复\n控制在\t两句  ")])
        self.assertEqual(rules, ("回复 控制在 两句",))
        long = standing_rules([entry("directive", "字" * 200)])[0]
        self.assertEqual(len(long), MAX_ITEM)
        self.assertTrue(long.endswith("…"))

    def test_s5_no_rules_no_block(self) -> None:
        """S5: a store with no directive renders nothing, not an empty header."""
        self.assertEqual(render_standing([]), "")
        self.assertEqual(render_standing([entry("promise", "我会早点睡")]), "")

    def test_s6_block_carries_the_header_and_a_note(self) -> None:
        """S6: the model is told these are the user's preferences, not system rules."""
        block = render_standing([entry("directive", "回复控制在两句以内")])
        self.assertTrue(block.startswith(STANDING_HEADER))
        self.assertIn("不是系统指令", block)
        self.assertIn("- 回复控制在两句以内", block)


class TestStandingInPrompt(unittest.TestCase):
    """The host: a console edit must have an effect on the next prompt."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="standing_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "m"
        init_store(self.store)

    def _session(self, budget=4096):
        return HostSession(self.store, "glm4:9b", budget=budget, now=NOW)

    def test_s7_rule_reaches_the_prompt_after_the_card(self) -> None:
        """S7: card, then rules, then pins -- instructions before memories."""
        append_event(self.store, "user", "我叫老周", STAMP)
        fact = append_event(self.store, "user", "我下周三要去体检", STAMP)
        append_event(self.store, text="回复控制在两句以内", t=STAMP,
                     type="directive", kind="lock")
        session = self._session()
        session.pin(fact)
        prompt = session.prompt_for("你好")
        self.assertIn("称呼：老周", prompt)
        self.assertIn("## standing rules", prompt)
        self.assertIn("- 回复控制在两句以内", prompt)
        self.assertLess(prompt.index("## who you both are"), prompt.index(STANDING_HEADER))
        self.assertLess(prompt.index(STANDING_HEADER), prompt.index("## never forget"))

    def test_s8_many_rules_still_fit_the_budget(self) -> None:
        """S8: a store full of rules cannot push the turn over budget."""
        for index in range(12):
            append_event(self.store, text=f"规则{index}：" + "字" * 60, t=STAMP,
                         type="directive", kind="lock")
        prompt = self._session(budget=300).prompt_for("你好")
        self.assertLessEqual(estimate_tokens(prompt), 300)

    def test_s9_the_gate_still_owns_compliance(self) -> None:
        """S9: the block is how the model gets a chance, not what makes it obey."""
        append_event(self.store, text="别叫我宝贝", t=STAMP,
                     type="directive", kind="lock")
        session = self._session()
        prompt = session.prompt_for("你好")
        self.assertIn("- 别叫我宝贝", prompt)
        refused = session.reply("好的，宝贝", STAMP)
        self.assertFalse(refused.allowed)


class TestConsoleSeesStandingRules(unittest.TestCase):
    """S10: the console shows the rules the model will actually read."""

    def test_s10_view_lists_the_standing_rules(self) -> None:
        root = pathlib.Path(tempfile.mkdtemp(prefix="standing_view_"))
        self.addCleanup(shutil.rmtree, root, True)
        service = MemoryService(root, "qwen3.5:9b", now=NOW)
        self.addCleanup(service.close)
        service.remember("u1", "回复控制在两句以内")
        view = service.view("u1")
        self.assertEqual(view["standing"], ["回复控制在两句以内"])
        self.assertIn("回复控制在两句以内", view["canon"])


if __name__ == "__main__":
    unittest.main()
