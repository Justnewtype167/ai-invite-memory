"""M16: persona events are skipped by the kernel, so identity never moves.

Two guarantees are under test here:

1. A ``refusal`` event (M13) no longer breaks compilation.
2. Each of the six persona shapes can be appended a hundred times and the
   kernel stays byte-identical: same kid, same head, same ``self.md``,
   ``canon.md``, ``state.json`` and ``graph.json``. Incremental compilation
   and reconciliation agree with the full compile.
"""

from __future__ import annotations

import hashlib
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

from jian.canonical import dumps
from jian.capsule import (
    append_event,
    append_payload_event,
    append_refusal,
    event_full_text,
    init_store,
)
from jian.event import parse_event
from jian_kernel.compiler import compile_kernel, core_events, read_evidence
from jian_kernel.history import record_kernel, verify_kernel
from jian_kernel.incremental import compile_kernel_incremental, reconcile
from jian_kernel.kernel import HISTORY_FILE, KERNEL_DIR, Policy
from jian_persona.errors import (
    E_PERSONA_BUDGET,
    E_PERSONA_INPUT,
    E_PERSONA_REDACTION,
    E_PERSONA_STYLE_CARD,
    E_PERSONA_TRAIT_CAP,
    E_PERSONA_TRAIT_CONFLICT,
    E_PERSONA_TRAIT_MODE,
    E_PERSONA_TRAIT_SCHEMA,
    E_PERSONA_UNAPPROVED,
    PersonaError,
)
from jian_persona.style_card import (
    assert_redacted,
    echo_guard,
    load_style_card,
    parse_style_card,
    record_style_card,
    style_input,
)
from jian_persona.traits import load_vocabulary, resolve_traits
from jian_persona.user_card import UserCard, derive_user_card, pin_user_card
from jian_persona.view import build_persona_view
from jian_recall.assemble import Context, ContextItem

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = "2026-01-05T10:00:00+08:00"
TRACE = "sha256:" + hashlib.sha256(b"trace").hexdigest()
PROMPT_SHA = "b" * 16
MODEL = "test-model"
PERSONA_PER_SHAPE = 100
SEED_EVENTS = 5
SCRIPT = (
    "import sys\n"
    "from pathlib import Path\n"
    "from jian.canonical import dumps\n"
    "from jian_kernel.compiler import read_evidence\n"
    "from jian_persona.user_card import derive_user_card\n"
    "card = derive_user_card(read_evidence(Path(sys.argv[1])))\n"
    "sys.stdout.write(dumps(card.to_payload()).decode('utf-8'))\n"
)


def _seed(store: pathlib.Path) -> None:
    """Write five kernel events that survive the persona skip list."""
    append_event(store, "user", "今天天气不错", "2026-01-01T09:00:00Z")
    append_event(
        store, None, "以后不许半夜打电话", "2026-01-02T09:00:00Z",
        type="directive", kind="lock",
    )
    append_event(store, "user", "妈妈下周三做手术", "2026-01-03T09:00:00Z")
    append_event(
        store, None, "升职了", "2026-01-04T09:00:00Z", type="milestone"
    )
    append_event(
        store, None, "谢谢你记得", "2026-01-04T10:00:00Z",
        type="feedback", kind="praise",
    )


def _stamp(index: int) -> str:
    """Return a unique stamp for persona event ``index``."""
    moment = datetime(2026, 1, 5, tzinfo=timezone.utc) + timedelta(seconds=index)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _append_refusals(store: pathlib.Path, offset: int) -> None:
    for index in range(PERSONA_PER_SHAPE):
        append_refusal(
            store, "text", "gate_rule", TRACE, _stamp(offset + index)
        )


def _append_trait_directive(store: pathlib.Path, offset: int, kind: str) -> None:
    for index in range(PERSONA_PER_SHAPE):
        append_event(
            store, None, "人格特质写入", _stamp(offset + index),
            type="directive", kind=kind,
        )


def _append_persona_proposal(store: pathlib.Path, offset: int, target: str) -> None:
    for index in range(PERSONA_PER_SHAPE):
        append_event(
            store, None, "人格产物提议", _stamp(offset + index),
            type="proposal", target=target, model=MODEL, prompt_sha=PROMPT_SHA,
        )


def _append_all_persona(store: pathlib.Path) -> None:
    """Append the six persona shapes, one hundred each (600 events)."""
    _append_refusals(store, 0)
    _append_trait_directive(store, 100, "trait")
    _append_trait_directive(store, 200, "trait_off")
    _append_persona_proposal(store, 300, "self.trait")
    _append_persona_proposal(store, 400, "self.style_card")
    _append_persona_proposal(store, 500, "self.user_card")


class TestPersonaSkip(unittest.TestCase):
    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_persona_"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _store(self, name: str, seed: bool = True) -> pathlib.Path:
        store = self.root / name
        init_store(store)
        if seed:
            _seed(store)
        return store

    def test_refusal_compiles(self) -> None:
        """A refusal joins the chain but changes no kernel artifact."""
        clean = self._store("clean")
        with_refusal = self._store("with_refusal")
        policy = Policy(now=NOW)
        expected = compile_kernel(clean, policy)
        append_refusal(
            with_refusal, "text", "gate_rule", TRACE, "2026-01-05T09:00:00Z"
        )
        actual = compile_kernel(with_refusal, policy)
        print(
            f"M16 refusal kid={actual.kid[:12]} head={actual.head} "
            f"expected={expected.kid[:12]}"
        )
        self.assertEqual(actual.kid, expected.kid)
        self.assertEqual(actual.head, expected.head)
        self.assertEqual(actual.self_md, expected.self_md)
        self.assertEqual(actual.canon_md, expected.canon_md)
        self.assertEqual(actual.state, expected.state)
        self.assertEqual(dumps(actual.graph_payload()), dumps(expected.graph_payload()))

    def test_persona_events_keep_kid(self) -> None:
        """Six persona shapes, 100 each: the kernel stays byte-identical."""
        store = self._store("store")
        policy = Policy(now=NOW)
        before = compile_kernel(store, policy)
        incremental_before = compile_kernel_incremental(store, policy)
        self.assertEqual(incremental_before.kid, before.kid)

        _append_all_persona(store)

        after = compile_kernel(store, policy)
        print(
            f"M16 persona events=600 kid={after.kid[:12]} head={after.head} "
            f"stable={after.kid == before.kid}"
        )
        self.assertEqual(after.kid, before.kid)
        self.assertEqual(after.head, before.head)
        self.assertEqual(after.self_md, before.self_md)
        self.assertEqual(after.canon_md, before.canon_md)
        self.assertEqual(after.state, before.state)
        self.assertEqual(dumps(after.graph_payload()), dumps(before.graph_payload()))
        self.assertEqual(after.files(1), before.files(1))

        incremental_after = compile_kernel_incremental(store, policy)
        self.assertEqual(incremental_after.kid, before.kid)
        self.assertEqual(incremental_after.head, before.head)
        self.assertEqual(incremental_after.self_md, before.self_md)

        report = reconcile(store, policy)
        self.assertEqual(report.head, before.head)
        self.assertEqual(report.events, SEED_EVENTS)
        self.assertEqual(report.kid, before.kid)

    def test_record_persona_only_keeps_version(self) -> None:
        """A trait-only advance leaves the version ledger byte-identical."""
        store = self._store("record")
        first = record_kernel(store, Policy(now=NOW))
        self.assertEqual(first.version, 1)
        self.assertTrue(first.written)
        ledger = store / KERNEL_DIR / HISTORY_FILE
        before_bytes = ledger.read_bytes()

        append_event(
            store, None, "人格特质写入", "2026-01-05T09:00:00Z",
            type="directive", kind="trait",
        )

        second = record_kernel(store, Policy(now=NOW))
        print(
            f"M16 persona-only version={second.version} written={second.written} "
            f"kid_stable={second.kid == first.kid}"
        )
        self.assertEqual(second.version, 1)
        self.assertEqual(second.kid, first.kid)
        self.assertFalse(second.written)
        self.assertEqual(ledger.read_bytes(), before_bytes)

        report = verify_kernel(store)
        self.assertEqual(report.version, 1)
        self.assertEqual(report.kid, first.kid)

        events = read_evidence(store)
        self.assertEqual(events[-1].type, "directive")
        self.assertEqual(events[-1].kind, "trait")


class TestTraits(unittest.TestCase):
    VOCAB = ("可爱", "毒舌", "闷骚", "温柔", "高冷", "话痨")

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_traits_"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _store(self) -> pathlib.Path:
        store = self.root / "store"
        init_store(store)
        return store

    def _vocab_file(self, payload: object) -> pathlib.Path:
        path = self.root / "vocab.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        return path

    def _enable(self, store: pathlib.Path, name: str, offset: int) -> None:
        append_event(
            store, None, f"启用特质 {name}", _stamp(offset),
            type="directive", kind="trait",
        )

    def test_traits_schema(self) -> None:
        """Vocabulary entries are validated field by field."""
        vocabulary = load_vocabulary()
        self.assertEqual(sorted(vocabulary), sorted(self.VOCAB))
        cases = (
            (
                {"x": _entry(modes=["party"])},
                E_PERSONA_TRAIT_MODE,
            ),
            (
                {"x": _entry(conflicts=["不存在"])},
                E_PERSONA_TRAIT_CONFLICT,
            ),
            (
                {"x": {"conflicts": [], "modes": ["support"], "risk": "low"}},
                E_PERSONA_TRAIT_SCHEMA,
            ),
            (
                {"x": _entry(risk="extreme")},
                E_PERSONA_TRAIT_SCHEMA,
            ),
        )
        for payload, code in cases:
            path = self._vocab_file(payload)
            with self.assertRaises(PersonaError) as caught:
                load_vocabulary(path)
            self.assertEqual(caught.exception.code, code)
        print(f"M16 traits vocabulary={len(vocabulary)} schema_cases={len(cases)}")

    def test_trait_cap_and_conflict(self) -> None:
        """The sixth active trait is rejected; 可爱 beats 毒舌."""
        vocabulary = load_vocabulary()
        store = self._store()
        for index, name in enumerate(self.VOCAB):
            self._enable(store, name, index)
        with self.assertRaises(PersonaError) as caught:
            resolve_traits(read_evidence(store), vocabulary, "support")
        self.assertEqual(caught.exception.code, E_PERSONA_TRAIT_CAP)

        store = self._store_conflict()
        resolution = resolve_traits(read_evidence(store), vocabulary, "support")
        names = [item.name for item in resolution.active]
        print(f"M16 traits conflict active={names} cap={E_PERSONA_TRAIT_CAP}")
        self.assertIn("可爱", names)
        self.assertNotIn("毒舌", names)
        self.assertEqual(len(resolution.conflicts), 1)
        item = resolution.conflicts[0]
        self.assertEqual(item.winner, "可爱")
        self.assertEqual(item.loser, "毒舌")
        self.assertIn("### Conflicts", resolution.conflicts_md())
        self.assertIn("可爱", resolution.conflicts_md())
        self.assertIn("毒舌", resolution.conflicts_md())

    def _store_conflict(self) -> pathlib.Path:
        store = self.root / "conflict"
        init_store(store)
        self._enable(store, "可爱", 10)
        self._enable(store, "毒舌", 11)
        return store

    def test_trait_requires_event(self) -> None:
        """No trait event means no trait; an unapproved proposal fails."""
        vocabulary = load_vocabulary()
        store = self._store()
        self.assertEqual(resolve_traits([], vocabulary, "support").active, ())

        proposal = append_event(
            store, None, "提议特质 毒舌", _stamp(20),
            type="proposal", target="self.trait", model=MODEL,
            prompt_sha=PROMPT_SHA,
        )
        with self.assertRaises(PersonaError) as caught:
            resolve_traits(read_evidence(store), vocabulary, "support")
        self.assertEqual(caught.exception.code, E_PERSONA_UNAPPROVED)

        append_event(
            store, None, "提议特质 毒舌", _stamp(21),
            type="directive", kind="trait", target=proposal.id,
        )
        resolution = resolve_traits(read_evidence(store), vocabulary, "banter")
        names = [item.name for item in resolution.active]
        print(f"M16 traits approved proposal={proposal.id} active={names}")
        self.assertEqual(names, ["毒舌"])
        self.assertEqual(resolution.active[0].origin, "approved_proposal")
        self.assertEqual(resolution.active[0].event_id, proposal.id)

    def test_trait_mode_gate(self) -> None:
        """A high-risk trait outside its modes is dropped with a reason."""
        vocabulary = load_vocabulary()
        store = self._store()
        self._enable(store, "毒舌", 30)
        events = read_evidence(store)
        consult = resolve_traits(events, vocabulary, "consult")
        banter = resolve_traits(events, vocabulary, "banter")
        print(
            f"M16 traits mode consult={[i.name for i in consult.active]} "
            f"banter={[i.name for i in banter.active]}"
        )
        self.assertEqual(consult.active, ())
        self.assertTrue(consult.reasons)
        self.assertTrue(any("毒舌" in item and "consult" in item
                            for item in consult.reasons))
        self.assertEqual([item.name for item in banter.active], ["毒舌"])


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
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_style_"))
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
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_user_card_"))
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


def _entry(
    guidance: str = "guidance",
    conflicts: list[str] | None = None,
    modes: list[str] | None = None,
    risk: str = "low",
) -> dict[str, object]:
    return {
        "guidance": guidance,
        "conflicts": conflicts if conflicts is not None else [],
        "modes": modes if modes is not None else ["support"],
        "risk": risk,
    }


if __name__ == "__main__":
    unittest.main()
