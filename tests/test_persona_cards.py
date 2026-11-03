"""M16: style card, user card and the shared persona view.

Every artifact here is derived from evidence but never enters the kernel kid:

* the style card is distilled once and written as a v2 proposal,
* the user card is recomputed mechanically and must be byte-identical,
* the persona view stacks the four prompt groups without touching PCS rules.

Kernel skip-list tests and the trait vocabulary are in ``tests/test_persona.py``.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from aiinvite.canonical import dumps
from aiinvite.capsule import (
    append_event,
    append_payload_event,
    event_full_text,
    init_store,
)
from aiinvite.event import parse_event
from aiinvite.kernel.compiler import compile_kernel, core_events, read_evidence
from aiinvite.kernel.incremental import compile_kernel_incremental
from aiinvite.kernel.kernel import Policy
from aiinvite.persona.errors import (
    E_PERSONA_BUDGET,
    E_PERSONA_INPUT,
    E_PERSONA_REDACTION,
    E_PERSONA_STYLE_CARD,
    PersonaError,
)
from aiinvite.persona.style_card import (
    assert_redacted,
    echo_guard,
    load_style_card,
    parse_style_card,
    record_style_card,
    style_input,
)
from aiinvite.persona.user_card import UserCard, derive_user_card, pin_user_card
from aiinvite.persona.view import build_persona_view
from aiinvite.pcs.probes import load_rules_v2
from aiinvite.recall.assemble import Context, ContextItem

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = "2026-01-05T10:00:00+08:00"
PROMPT_SHA = "b" * 16
MODEL = "test-model"
SCRIPT = (
    "import sys\n"
    "from pathlib import Path\n"
    "from aiinvite.canonical import dumps\n"
    "from aiinvite.kernel.compiler import read_evidence\n"
    "from aiinvite.persona.user_card import derive_user_card\n"
    "card = derive_user_card(read_evidence(Path(sys.argv[1])))\n"
    "sys.stdout.write(dumps(card.to_payload()).decode('utf-8'))\n"
)


def _stamp(index: int) -> str:
    """Return a unique stamp for event ``index``."""
    moment = datetime(2026, 1, 5, tzinfo=timezone.utc) + timedelta(seconds=index)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _last_evidence_json(store: pathlib.Path) -> dict[str, object]:
    """Return the decoded last evidence line of a store."""
    lines: list[str] = []
    for path in sorted((store / "evidence").glob("seg-*.jsonl")):
        lines.extend(
            line for line in path.read_text(encoding="utf-8").splitlines() if line
        )
    return json.loads(lines[-1])


def _card_payload(
    examples: list[str] | None = None,
    counter_examples: list[str] | None = None,
) -> dict[str, object]:
    """Return one minimal valid style-card payload."""
    return {
        "source": {"from_event": "ev_000001", "to_event": "ev_000500", "count": 500},
        "distilled_at": "2026-01-05T10:00:00Z",
        "model": MODEL,
        "prompt_sha": PROMPT_SHA,
        "rhythm": "短句为主",
        "address": "直接叫你",
        "tics": ["嗯"],
        "examples": ["今天天气不错"] if examples is None else examples,
        "counter_examples": ["综上所述"] if counter_examples is None else counter_examples,
        "forbidden": ["宝贝"],
    }


def _card_evidence(card: UserCard) -> list[str]:
    """Collect every evidence id referenced by one non-empty card entry."""
    found: list[str] = []
    address = card.address
    for key in ("call_evidence", "self_evidence"):
        value = address.get(key)
        if isinstance(value, str) and value:
            found.append(value)
    never = address.get("never")
    assert isinstance(never, list)
    for item in never:
        found.append(str(item["evidence"]))
    for group in (card.people, card.taboos, card.promises, card.ongoing):
        for item in group:
            found.append(str(item["evidence"]))
    for key in ("like", "dislike"):
        for item in card.prefs[key]:
            found.append(str(item["evidence"]))
    return found


class TestStyleCard(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_style_"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _store(self) -> pathlib.Path:
        store = self.root / "store"
        init_store(store)
        return store

    def test_style_card_schema(self) -> None:
        """Card limits reject 801 characters, 16 examples, 4 counters."""
        payload = _card_payload()
        card = parse_style_card(dumps(payload).decode("utf-8"))
        self.assertEqual(card.to_payload(), payload)

        oversized = _card_payload()
        oversized["rhythm"] = ""
        size = len(dumps(oversized).decode("utf-8"))
        oversized["rhythm"] = "x" * (801 - size)
        self.assertEqual(len(dumps(oversized).decode("utf-8")), 801)
        missing = _card_payload()
        del missing["rhythm"]
        cases = (
            oversized,
            _card_payload(examples=[f"e{index}" for index in range(16)]),
            _card_payload(counter_examples=[f"c{index}" for index in range(4)]),
            missing,
        )
        for bad in cases:
            with self.assertRaises(PersonaError) as caught:
                parse_style_card(dumps(bad).decode("utf-8"))
            self.assertEqual(caught.exception.code, E_PERSONA_STYLE_CARD)

        store = self._store()
        event = record_style_card(store, card)
        data = _last_evidence_json(store)
        parsed = parse_event(data)
        self.assertEqual(parsed.v, 2)
        self.assertEqual(parsed.type, "proposal")
        self.assertEqual(parsed.target, "self.style_card")
        self.assertEqual(parsed.summary, "style card 500 events")
        self.assertEqual(data["id"], event.id)
        self.assertEqual(event_full_text(store, data), card.text())
        loaded = load_style_card(store)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.to_payload(), card.to_payload())
        print(
            f"M16 style card chars={len(card.text())} schema_cases={len(cases)} "
            f"event={event.id}"
        )

    def test_style_card_redaction(self) -> None:
        """Third-party text never enters the input or survives a card check."""
        store = self._store()
        secret = "这是第三方不愿被复述的原话"
        third = append_payload_event(
            store, "text", secret, secret.encode("utf-8"), role="user",
            t="2026-01-01T09:00:00Z",
        )
        visible = "今天天气不错"
        append_payload_event(
            store, "text", visible, visible.encode("utf-8"), role="user",
            t="2026-01-02T09:00:00Z",
        )
        events = read_evidence(store)
        excluded = {third.id: "third_party"}

        window = style_input(events, excluded)
        self.assertEqual(window.count, 1)
        self.assertNotIn(secret, window.text)

        leaked = _card_payload(examples=[secret])
        card = parse_style_card(dumps(leaked).decode("utf-8"))
        with self.assertRaises(PersonaError) as caught:
            assert_redacted(card, [secret])
        self.assertEqual(caught.exception.code, E_PERSONA_REDACTION)

        record_style_card(store, card)
        with self.assertRaises(PersonaError) as caught:
            load_style_card(store, excluded)
        self.assertEqual(caught.exception.code, E_PERSONA_REDACTION)

        with self.assertRaises(PersonaError) as caught:
            style_input(events, {third.id: "bogus"})
        self.assertEqual(caught.exception.code, E_PERSONA_INPUT)
        print(
            f"M16 style redaction excluded={third.id} "
            f"window={window.from_event}..{window.to_event}"
        )

    def test_echo_guard(self) -> None:
        """A 13-character overlap is an echo; 12 characters is allowed."""
        thirteen = "abcdefghijklm"
        twelve = "abcdefghijkl"
        examples = ["prefix-" + thirteen + "-suffix"]
        heavy = echo_guard(thirteen, examples)
        light = echo_guard(twelve, examples)
        print(f"M16 echo lcs13={heavy.lcs} ok={heavy.ok} lcs12={light.lcs} ok={light.ok}")
        self.assertEqual(heavy.lcs, 13)
        self.assertFalse(heavy.ok)
        self.assertEqual(light.lcs, 12)
        self.assertTrue(light.ok)
        self.assertEqual(echo_guard("完全不同的一句", examples).lcs, 0)


class TestUserCard(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_user_card_"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _store(self, name: str = "store") -> pathlib.Path:
        store = self.root / name
        init_store(store)
        return store

    def _seed_facts(self, store: pathlib.Path) -> None:
        append_event(store, "user", "不许叫宝贝", "2026-01-01T09:00:00Z")
        append_event(store, "user", "以后叫我小林", "2026-01-02T09:00:00Z")
        append_event(store, "user", "自称本姑娘", "2026-01-03T09:00:00Z")
        append_event(store, "user", "妈妈叫桂花", "2026-01-04T09:00:00Z")
        append_event(
            store, None, "以后不许半夜打电话", "2026-01-05T09:00:00Z",
            type="directive", kind="lock",
        )
        append_event(store, "user", "答应下周给你打电话", "2026-01-06T09:00:00Z")
        append_event(store, "user", "我喜欢喝茶", "2026-01-07T09:00:00Z")
        append_event(store, "user", "我不喜欢吃香菜", "2026-01-08T09:00:00Z")
        append_event(store, None, "升职了", "2026-01-09T09:00:00Z", type="milestone")

    def _address_card(self, *texts: str) -> UserCard:
        store = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_address_"))
        self.addCleanup(shutil.rmtree, store, True)
        init_store(store)
        for index, text in enumerate(texts):
            append_event(store, "user", text, _stamp(index))
        return derive_user_card(read_evidence(store))

    def test_address_plain_call(self) -> None:
        """A plain address directive sets the call name and no taboo."""
        card = self._address_card("叫我老周")
        print(
            f"M16 address plain call={card.address['call']} "
            f"never={card.address['never']}"
        )
        self.assertEqual(card.address["call"], "老周")
        self.assertEqual(card.address["never"], [])

    def test_address_negation_be_drops_earlier_call(self) -> None:
        """An earlier call equal to a later taboo is dropped, not kept."""
        card = self._address_card("叫我宝贝", "别叫我宝贝")
        names = [item["text"] for item in card.address["never"]]
        print(f"M16 address 别 call={card.address['call']!r} never={names}")
        self.assertEqual(card.address["call"], "")
        self.assertNotIn("call_evidence", card.address)
        self.assertEqual(names, ["宝贝"])

    def test_address_negation_buyao_is_taboo(self) -> None:
        """``不要叫我X`` is a taboo, never the call name."""
        card = self._address_card("不要叫我宝贝")
        names = [item["text"] for item in card.address["never"]]
        print(f"M16 address 不要 call={card.address['call']!r} never={names}")
        self.assertEqual(card.address["call"], "")
        self.assertEqual(names, ["宝贝"])

    def test_address_negation_buxu_is_taboo(self) -> None:
        """``不许叫我X`` is a taboo, never the call name."""
        card = self._address_card("不许叫我小名")
        names = [item["text"] for item in card.address["never"]]
        print(f"M16 address 不许 call={card.address['call']!r} never={names}")
        self.assertEqual(card.address["call"], "")
        self.assertEqual(names, ["小名"])

    def test_address_negation_beng_is_taboo(self) -> None:
        """``甭叫我X`` is decided by the clause, not by a known prefix."""
        card = self._address_card("甭叫我宝宝")
        names = [item["text"] for item in card.address["never"]]
        print(f"M16 address 甭 call={card.address['call']!r} never={names}")
        self.assertEqual(card.address["call"], "")
        self.assertEqual(names, ["宝宝"])

    def test_address_negation_wu_is_taboo(self) -> None:
        """``勿叫我X`` is a taboo."""
        card = self._address_card("勿叫我小名")
        names = [item["text"] for item in card.address["never"]]
        print(f"M16 address 勿 call={card.address['call']!r} never={names}")
        self.assertEqual(card.address["call"], "")
        self.assertEqual(names, ["小名"])

    def test_address_negation_bielao_is_taboo(self) -> None:
        """``别老叫我X`` is a taboo."""
        card = self._address_card("别老叫我小名")
        names = [item["text"] for item in card.address["never"]]
        print(f"M16 address 别老 call={card.address['call']!r} never={names}")
        self.assertEqual(card.address["call"], "")
        self.assertEqual(names, ["小名"])

    def test_address_negation_buyong_is_taboo(self) -> None:
        """``不用叫我X`` is a taboo."""
        card = self._address_card("不用叫我小名")
        names = [item["text"] for item in card.address["never"]]
        print(f"M16 address 不用 call={card.address['call']!r} never={names}")
        self.assertEqual(card.address["call"], "")
        self.assertEqual(names, ["小名"])

    def test_address_strips_suffixes(self) -> None:
        """Hesitation tails such as 就好 never become part of the name."""
        tails = ("就好", "就行", "吧", "啊", "哦", "了", "啦")
        for tail in tails:
            card = self._address_card("叫我老周" + tail)
            self.assertEqual(card.address["call"], "老周", tail)
        card = self._address_card("叫我老周就好吧")
        print(
            f"M16 address suffix call={card.address['call']!r} "
            f"tails={len(tails)}"
        )
        self.assertEqual(card.address["call"], "老周")

    def test_address_self_intro_sets_call(self) -> None:
        """``我叫X`` is a self-introduction, not a missing pronoun."""
        card = self._address_card("我叫老周")
        print(
            f"M16 address self-intro call={card.address['call']!r} "
            f"never={card.address['never']}"
        )
        self.assertEqual(card.address["call"], "老周")
        self.assertEqual(card.address["never"], [])

    def test_address_name_field_sets_call(self) -> None:
        """``名字：X；...`` stops at the separator instead of eating the tail."""
        card = self._address_card("名字：张兰；三十岁")
        print(
            f"M16 address name-field call={card.address['call']!r} "
            f"never={card.address['never']}"
        )
        self.assertEqual(card.address["call"], "张兰")
        self.assertEqual(card.address["never"], [])
        card = self._address_card("名字是张兰")
        self.assertEqual(card.address["call"], "张兰")

    def test_address_negation_without_call(self) -> None:
        """``别叫我X`` alone stays a taboo and leaves the call empty."""
        card = self._address_card("别叫我宝贝")
        names = [item["text"] for item in card.address["never"]]
        print(f"M16 address negation-only call={card.address['call']!r} "
              f"never={names}")
        self.assertEqual(card.address["call"], "")
        self.assertEqual(names, ["宝贝"])

    def test_address_kinship_call_is_not_call(self) -> None:
        """``我妈叫我回家`` is someone else calling, not the user's address."""
        card = self._address_card("我妈叫我回家")
        print(
            f"M16 address kinship call={card.address['call']!r} "
            f"never={card.address['never']}"
        )
        self.assertEqual(card.address["call"], "")
        self.assertEqual(card.address["never"], [])

    def test_user_card_deterministic(self) -> None:
        """The same evidence yields byte-identical cards in two processes."""
        store = self._store()
        self._seed_facts(store)
        events = read_evidence(store)
        first = derive_user_card(events)
        second = derive_user_card(events)
        self.assertEqual(first.to_payload(), second.to_payload())
        expected = dumps(first.to_payload()).decode("utf-8")

        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        completed = subprocess.run(
            [sys.executable, "-c", SCRIPT, str(store)],
            cwd=str(ROOT), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=True,
        )
        self.assertEqual(completed.stdout, expected)
        print(
            f"M16 user card deterministic bytes={len(expected)} "
            f"call={first.address.get('call')}"
        )

    def test_user_card_traceable(self) -> None:
        """Every non-empty entry points at real evidence; removing it empties it."""
        store = self._store()
        self._seed_facts(store)
        events = read_evidence(store)
        card = derive_user_card(events)
        valid = {event.event_id for event in core_events(events)}
        evidence = _card_evidence(card)
        self.assertTrue(evidence)
        for event_id in evidence:
            self.assertIn(event_id, valid)
        self.assertEqual(card.address["call"], "小林")
        self.assertEqual(card.address["self"], "本姑娘")

        call_event = str(card.address["call_evidence"])
        shrunk = derive_user_card(
            [event for event in events if event.event_id != call_event]
        )
        self.assertEqual(shrunk.address["call"], "")
        self.assertNotIn("call_evidence", shrunk.address)

        promise_event = str(card.promises[0]["evidence"])
        self.assertTrue(card.promises)
        remaining = derive_user_card(
            [event for event in events if event.event_id != promise_event]
        )
        self.assertEqual(remaining.promises, ())
        print(
            f"M16 user card traceable entries={len(evidence)} "
            f"call={call_event} promise={promise_event}"
        )

    def test_user_card_budget_and_pin(self) -> None:
        """The card renders under 400 chars and stays pinned first in context."""
        store = self._store("bulk")
        self._seed_facts(store)
        for index in range(6):
            append_event(
                store, None, "第%d条忌讳：" % index + "不许这样做" * 10,
                _stamp(index), type="directive", kind="lock",
            )
        events = read_evidence(store)
        card = derive_user_card(events)
        text = card.text()
        self.assertLessEqual(len(text), 400)
        self.assertGreaterEqual(len(text), 250)
        self.assertEqual(card.text(), derive_user_card(events).text())
        self.assertIn("称呼：小林", text)

        items = (
            ContextItem("ev_000001", "recent", 2500, "a" * 10),
            ContextItem("ev_000002", "retrieved", 2500, "b" * 10),
        )
        context = Context(5000, items, 2)
        pinned = pin_user_card(context, card, budget=4096)
        self.assertEqual(pinned.items[0].event_id, "user_card")
        self.assertEqual(pinned.items[0].slot, "pinned")
        self.assertEqual(pinned.items[0].text, text)
        self.assertLessEqual(pinned.total_tokens, 4096)
        self.assertEqual([item.event_id for item in pinned.items[1:]], ["ev_000001"])

        with self.assertRaises(PersonaError) as caught:
            pin_user_card(Context(0, (), 0), card, budget=1)
        self.assertEqual(caught.exception.code, E_PERSONA_BUDGET)
        print(
            f"M16 user card budget chars={len(text)} "
            f"pinned_tokens={pinned.items[0].tokens} total={pinned.total_tokens}"
        )

    def test_user_card_not_in_kid(self) -> None:
        """Two different user cards cannot move the kernel kid."""
        store = self._store()
        self._seed_facts(store)
        policy = Policy(now=NOW)
        kernel = compile_kernel(store, policy)
        card_a = derive_user_card(read_evidence(store))
        card_b = replace(
            card_a,
            address={"call": "大王", "self": "臣", "never": []},
        )
        view_a = build_persona_view(store, user_card=card_a, policy=policy)
        view_b = build_persona_view(store, user_card=card_b, policy=policy)
        print(
            f"M16 user card kid={kernel.kid[:12]} "
            f"a={view_a.kid[:12]} b={view_b.kid[:12]}"
        )
        self.assertEqual(view_a.kid, kernel.kid)
        self.assertEqual(view_b.kid, kernel.kid)
        self.assertEqual(view_a.head, kernel.head)
        self.assertNotEqual(view_a.to_prompt("D"), view_b.to_prompt("D"))


class TestPersonaView(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_view_"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _store(self) -> pathlib.Path:
        store = self.root / "store"
        init_store(store)
        append_event(store, "user", "今天有点累", "2026-01-01T09:00:00Z")
        append_event(
            store, None, "启用特质 可爱", "2026-01-02T09:00:00Z",
            type="directive", kind="trait",
        )
        return store

    def _view(self):
        store = self._store()
        card = parse_style_card(dumps(_card_payload()).decode("utf-8"))
        return build_persona_view(
            store, style_card=card, policy=Policy(now=NOW)
        )

    def test_persona_not_in_pcs(self) -> None:
        """Persona text stays out of PCS rules; the four groups stack up."""
        view = self._view()
        body_a = view.to_prompt("A")
        body_b = view.to_prompt("B")
        body_c = view.to_prompt("C")
        body_d = view.to_prompt("D")
        self.assertEqual(body_a, "")
        self.assertIn("## Traits", body_b)
        self.assertNotIn("## Style", body_b)
        self.assertIn("## Style", body_c)
        self.assertNotIn("## User", body_c)
        self.assertIn("## User", body_d)
        with self.assertRaises(PersonaError) as caught:
            view.to_prompt("E")
        self.assertEqual(caught.exception.code, E_PERSONA_INPUT)

        self.assertIn("## Traits", view.self_md)
        self.assertIn("### Conflicts", view.self_md)
        self.assertIn("可爱", view.self_md)

        rules = load_rules_v2()
        rule_text = "\n".join(rule.text for rule in rules)
        self.assertNotIn("可爱", rule_text)
        self.assertNotIn("## Traits", rule_text)
        self.assertNotIn("## Style", rule_text)
        self.assertNotIn("## User", rule_text)
        for rule in rules:
            self.assertNotIn(rule.text, body_d)

        for path in sorted((ROOT / "aiinvite/persona").glob("*.py")):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("aiinvite.pcs", source, f"{path.name} imports aiinvite.pcs")
        print(
            f"M16 persona view groups="
            f"{[len(body) for body in (body_a, body_b, body_c, body_d)]} "
            f"rules={len(rules)}"
        )

    def test_passed_kernel_matches_internal_compile(self) -> None:
        """A supplied kernel yields exactly the internally compiled view."""
        store = self._store()
        policy = Policy(now=NOW)
        supplied = compile_kernel_incremental(store, policy)
        passed = build_persona_view(store, kernel=supplied, policy=policy)
        internal = build_persona_view(store, policy=policy)
        print(
            f"M16 view passed-kernel kid={passed.kid[:12]} "
            f"same={passed == internal}"
        )
        self.assertEqual(passed, internal)
        self.assertEqual(passed.kid, supplied.kid)
        self.assertEqual(passed.head, supplied.head)


if __name__ == "__main__":
    unittest.main()
