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
import pathlib
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from jian.canonical import dumps
from jian.capsule import append_event, append_refusal, init_store
from jian_kernel.compiler import compile_kernel, read_evidence
from jian_kernel.history import record_kernel, verify_kernel
from jian_kernel.incremental import compile_kernel_incremental, reconcile
from jian_kernel.kernel import HISTORY_FILE, KERNEL_DIR, Policy
from jian_persona.errors import (
    E_PERSONA_TRAIT_CAP,
    E_PERSONA_TRAIT_CONFLICT,
    E_PERSONA_TRAIT_MODE,
    E_PERSONA_TRAIT_SCHEMA,
    E_PERSONA_UNAPPROVED,
    PersonaError,
)
from jian_persona.traits import load_vocabulary, resolve_traits

NOW = "2026-01-05T10:00:00+08:00"
TRACE = "sha256:" + hashlib.sha256(b"trace").hexdigest()
PROMPT_SHA = "b" * 16
MODEL = "test-model"
PERSONA_PER_SHAPE = 100
SEED_EVENTS = 5


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
