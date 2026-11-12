"""M17: the reference host adapter keeps five calls and a fixed order."""
from __future__ import annotations

import inspect
import json
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from aiinvite.capsule import append_event, init_store, seal_store, verify_path
from aiinvite.kernel.compiler import compile_kernel
from aiinvite.kernel.kernel import Policy
from aiinvite.recall.index import evidence_files
from aiinvite.recall.tokenizer import estimate_tokens
from host_adapter import HostSession

NOW = "2026-11-01T10:00:00+08:00"
STAMP = "2026-11-01T09:00:00+08:00"


class TestHostAdapter(unittest.TestCase):
    """H1-H5: the adapter is a thin, ordered, read-mostly wrapper."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_host_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "mem"
        init_store(self.store)

    def _session(self) -> HostSession:
        session = HostSession(self.store, "qwen3.5:9b", now=NOW)
        session.on_user("我叫老周，别叫我宝贝", STAMP)
        return session

    def _events(self) -> list[dict[str, object]]:
        """Read every evidence event from disk, in chain order."""
        rows: list[dict[str, object]] = []
        for path in evidence_files(self.store):
            for line in path.read_text(encoding="utf-8").split("\n"):
                if line:
                    rows.append(json.loads(line))
        return rows

    def _evidence_bytes(self) -> dict[str, bytes]:
        """Snapshot evidence segments and the chain head byte-for-byte."""
        snapshot = {
            path.name: path.read_bytes()
            for path in sorted((self.store / "evidence").glob("seg-*.jsonl"))
        }
        snapshot["chain.json"] = (self.store / "chain.json").read_bytes()
        return snapshot

    def test_round_trip_records_two_turns(self) -> None:
        """H1: the adapter adds nothing beyond the two turns it writes.

        Turns are core evidence: they move ``events`` and ``known_days``, so the
        kid does move. The right assertion is that it moves exactly as far as a
        store written by ``append_event`` alone.
        """
        session = self._session()
        verdict = session.reply("在的。", "2026-11-01T09:01:00+08:00")
        self.assertTrue(verdict.allowed)
        self.assertEqual(verify_path(self.store).events, 2)
        self.assertEqual(session.stats()["turns"], 2)
        twin = self.root / "twin"
        init_store(twin)
        append_event(twin, "user", "我叫老周，别叫我宝贝", STAMP)
        append_event(twin, "assistant", "在的。", "2026-11-01T09:01:00+08:00")
        self.assertEqual(
            compile_kernel(self.store, Policy(now=NOW)).kid,
            compile_kernel(twin, Policy(now=NOW)).kid,
        )

    def test_prompt_order_is_fixed(self) -> None:
        """H2: rules, then the user card, then memory, then the input."""
        prompt = self._session().prompt_for("你好")
        marks = [prompt.index(m) for m in (
            "## behavior rules", "## who you both are",
            "## recent and recalled memory", "## persona", "## this turn")]
        self.assertEqual(marks, sorted(marks))
        self.assertTrue(prompt.endswith("你好"))

    def test_prompt_is_pure(self) -> None:
        """H3: asking twice writes nothing and returns identical bytes."""
        session = self._session()
        first = session.prompt_for("你好")
        events = verify_path(self.store).events
        second = session.prompt_for("你好")
        self.assertEqual(first, second)
        self.assertEqual(events, verify_path(self.store).events)

    def test_prompt_reads_evidence_once(self) -> None:
        """H5: one prompt parses the evidence once, not once per consumer.

        The kernel, the user card and the pins all want the same events. Each
        read is cheap when the cache is warm but not free on a large store, so
        the adapter passes one list down instead of asking three times.
        """
        session = self._session()
        reads: list[int] = []
        original = session._evidence.read

        def counted(store):
            reads.append(1)
            return original(store)

        session._evidence.read = counted
        session.prompt_for("你好")
        self.assertEqual(len(reads), 1)

    def test_refusal_is_recorded(self) -> None:
        """H4: a forbidden reply is recorded as a refusal, not as a turn."""
        append_event(self.store, text="别叫我宝贝", t=STAMP,
                     type="directive", kind="lock")
        seal_store(self.store)
        session = HostSession(self.store, "qwen3.5:9b", now=NOW)
        verdict = session.reply("宝贝我来了", "2026-11-01T09:05:00+08:00")
        self.assertFalse(verdict.allowed)
        self.assertEqual(session.stats()["turns"], 0)
        self.assertEqual(verify_path(self.store).events, 2)

    def test_prompt_respects_budget(self) -> None:
        """H5: the assembled prompt stays inside the token budget."""
        session = self._session()
        prompt = session.prompt_for("你好")
        self.assertLessEqual(estimate_tokens(prompt), 4096)

    def test_exactly_eight_public_methods(self) -> None:
        """H1: the adapter exposes exactly the calls the spec names.

        ``pin`` and ``unpin`` came with the unforgettable layer, ``learn_clues``
        with the clue cache: generating a clue costs about 12 s, so it is an
        explicit call the host schedules, never a hidden step inside a prompt.
        """
        public = {
            name for name, value in inspect.getmembers(HostSession, inspect.isfunction)
            if not name.startswith("_")
        }
        self.assertEqual(
            public,
            {
                "on_user", "on_assistant", "prompt_for", "reply", "stats",
                "pin", "unpin", "learn_clues",
            },
        )

    def test_prompt_does_not_touch_evidence(self) -> None:
        """H3: ``prompt_for`` writes no evidence and no chain bytes."""
        session = self._session()
        before = self._evidence_bytes()
        session.prompt_for("你好")
        session.prompt_for("你好")
        self.assertEqual(before, self._evidence_bytes())

    def test_refusal_is_one_gate_event_without_dialogue(self) -> None:
        """H4: a refused reply leaves exactly one refusal, never a turn."""
        append_event(self.store, text="别叫我宝贝", t=STAMP,
                     type="directive", kind="lock")
        seal_store(self.store)
        session = HostSession(self.store, "qwen3.5:9b", now=NOW)
        verdict = session.reply("宝贝我来了", "2026-11-01T09:05:00+08:00")
        self.assertFalse(verdict.allowed)
        rows = self._events()
        refusals = [row for row in rows if row["type"] == "refusal"]
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0]["kind"], "gate")
        self.assertEqual(refusals[0]["target"], "text")
        self.assertEqual(refusals[0]["text"], "禁称呼")
        self.assertNotIn("宝贝", str(refusals[0]["text"]))
        self.assertNotIn("我来了", str(refusals[0]["text"]))
        self.assertEqual(session.stats()["turns"], 0)
        self.assertEqual(
            [row for row in rows if row.get("role") == "assistant"], []
        )
        self.assertEqual(verify_path(self.store).events, len(rows))

    def test_allowed_reply_writes_no_refusal(self) -> None:
        """H4: a normal reply produces one assistant turn and no refusal."""
        session = self._session()
        verdict = session.reply("在的。", "2026-11-01T09:01:00+08:00")
        self.assertTrue(verdict.allowed)
        rows = self._events()
        self.assertEqual([row for row in rows if row["type"] == "refusal"], [])
        assistant = [row for row in rows if row.get("role") == "assistant"]
        self.assertEqual(len(assistant), 1)
        self.assertEqual(session.stats()["turns"], 2)

    def test_user_card_precedes_context(self) -> None:
        """H2: the card is pinned before memory, or it is not pinned at all."""
        prompt = self._session().prompt_for("你好")
        self.assertLess(
            prompt.index("## who you both are"),
            prompt.index("## recent and recalled memory"),
        )

    def test_single_event_store_prompt(self) -> None:
        """H5: one event still yields an in-budget prompt, card optional.

        An empty user card is omitted instead of shipping a ``- none`` block:
        the header costs tokens and tells the model nothing.
        """
        append_event(self.store, "user", "我叫老周", STAMP)
        session = HostSession(self.store, "qwen3.5:9b", now=NOW)
        prompt = session.prompt_for("你好")
        for header in ("## behavior rules", "## recent and recalled memory",
                       "## persona", "## this turn"):
            self.assertIn(header, prompt)
        if "## who you both are" in prompt:
            head, _, tail = prompt.partition("## who you both are")
            card = tail.split("## ", 1)[0]
            self.assertNotIn("- none", card)
        self.assertLessEqual(estimate_tokens(prompt), 4096)

    def test_empty_store_does_not_raise(self) -> None:
        """D1: a brand-new session can ask for a prompt before any turn."""
        session = HostSession(self.store, "qwen3.5:9b", now=NOW)
        prompt = session.prompt_for("你好")
        self.assertIn("## behavior rules", prompt)
        self.assertLessEqual(estimate_tokens(prompt), 4096)

    def test_long_input_is_truncated(self) -> None:
        """D2: budget covers the whole prompt, so the input is trimmed."""
        session = HostSession(self.store, "qwen3.5:9b", now=NOW)
        prompt = session.prompt_for("我" * 5000)
        self.assertLessEqual(estimate_tokens(prompt), 4096)

    def test_assistant_helper_is_not_a_gate(self) -> None:
        """D6: on_assistant is a replay helper, documented as ungated."""
        import inspect
        doc = inspect.getdoc(HostSession.on_assistant) or ""
        self.assertIn("Never use this for gated output", doc)

    TURNS = (
        "我叫老周",
        "别叫我宝贝",
        "我喜欢喝茶",
        "我妈叫我回家吃饭",
        "叫我一声宝贝",
        "我答应你明天早睡",
        "我不喜欢烟味",
        "名字是阿May",
        "搬家了",
    )

    def _card_block(self, session) -> str:
        return session._card_and_persona()[0]

    def test_incremental_card_matches_full_derivation(self) -> None:
        """P3: the folded card equals derive_user_card after every turn."""
        from aiinvite.kernel.compiler import read_evidence
        from aiinvite.persona.user_card import derive_user_card

        session = HostSession(self.store, "qwen3.5:9b", now=NOW)
        for text in self.TURNS:
            session.on_user(text, STAMP)
            session.on_assistant("好的，记下了", STAMP)
            session.prompt_for(text)
            expected = derive_user_card(read_evidence(self.store)).text().strip()
            folded = self._card_block(session).strip()
            if expected and expected != "- none":
                self.assertIn(expected, folded, "diverged after: " + text)

    def test_warm_session_matches_a_cold_one(self) -> None:
        """P3: continuing a folded session must equal starting it cold."""
        warm = HostSession(self.store, "qwen3.5:9b", now=NOW)
        for text in self.TURNS:
            warm.on_user(text, STAMP)
            warm.prompt_for(text)
        cold = HostSession(self.store, "qwen3.5:9b", now=NOW)
        self.assertEqual(cold.prompt_for("你好"), warm.prompt_for("你好"))


if __name__ == "__main__":
    unittest.main()
