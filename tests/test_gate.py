"""M13 V1-V6: the actuation gate, the single emit path and refusal evidence."""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import pathlib
import shutil
import tempfile
import unittest
from types import SimpleNamespace

from jian.capsule import append_event, append_refusal, init_store, verify_path
from jian.errors import E_SCHEMA, JianError
from jian_kernel.compiler import compile_kernel
from jian_kernel.kernel import CanonEntry, Policy

import jian_projection.gate as gate_module
from jian_projection import (
    Segment,
    Trace,
    Verdict,
    check,
    emit,
    load_gate_rules,
    trace_digest,
)
from jian_projection.errors import (
    E_PR_GATE_RULES,
    E_PR_GATE_SCOPE,
    ProjectionError,
)

NOW = "2026-10-29T10:00:00+08:00"
STAMP = "2026-10-29T09:00:00Z"
DIRECTIVE = "别叫我宝贝"
CLEAN_TEXT = "今天要早起，先喝杯水"
BAD_TEXT = "宝贝我来了"
PURE_RUNS = 100


def _fake_kernel(texts: tuple[str, ...]) -> SimpleNamespace:
    """Return a duck-typed kernel with canon entries but no store or clock."""
    canon = tuple(
        CanonEntry("directive", text, (f"ev_{index + 1:06d}",))
        for index, text in enumerate(texts)
    )
    return SimpleNamespace(kid="k" * 64, self_md="# Self\n", canon=canon)


def _text_trace(text: str, kid: str = "k" * 64) -> Trace:
    return Trace(kid, "text_v1", (Segment("text", text, None),))


class _CountingSink:
    """A sink that records how many times it was called."""

    def __init__(self) -> None:
        self.calls: list[Trace] = []

    def __call__(self, trace: Trace) -> None:
        self.calls.append(trace)


class TestGateSchema(unittest.TestCase):
    """V1: Verdict fields and rule-data validation with fixed error codes."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_gate_schema_"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _assert_code(self, code: str, payload: object) -> None:
        path = self.root / "rules.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ProjectionError) as caught:
            load_gate_rules(path)
        self.assertEqual(caught.exception.code, code)

    def test_verdict_fields(self) -> None:
        """V1: Verdict is a frozen four-field record."""
        names = [field.name for field in dataclasses.fields(Verdict)]
        self.assertEqual(names, ["allowed", "rule", "segment_index", "detail"])
        verdict = Verdict(True, None, None, "")
        self.assertTrue(verdict.allowed)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            verdict.allowed = False  # type: ignore[misc]

    def test_shipped_rules_load(self) -> None:
        """V1: the data file is named gate_rules.json and every rule validates."""
        self.assertEqual(gate_module.DATA_FILE.name, "gate_rules.json")
        rules = load_gate_rules()
        self.assertTrue(rules.rules)
        for rule in rules.rules:
            self.assertIn(rule.scope, gate_module.SCOPES)
            self.assertTrue(rule.canon_keywords)
        names = [rule.name for rule in rules.rules]
        self.assertIn("禁称呼", names)

    def test_bad_rules_report_codes(self) -> None:
        """V1: unknown scope and missing/bad fields map to their own codes."""
        self._assert_code(
            E_PR_GATE_SCOPE,
            {"坏作用域": {"canon_keywords": ["x"], "forbid_text": ["y"], "scope": "audio"}},
        )
        self._assert_code(E_PR_GATE_RULES, {"缺关键词": {"forbid_text": ["y"], "scope": "text"}})
        self._assert_code(E_PR_GATE_RULES, {"缺作用域": {"canon_keywords": ["x"], "forbid_text": ["y"]}})
        self._assert_code(
            E_PR_GATE_RULES,
            {"坏上限": {"canon_keywords": ["x"], "max_text_chars": True, "scope": "text"}},
        )
        self._assert_code(
            E_PR_GATE_RULES,
            {"无禁止": {"canon_keywords": ["x"], "scope": "text"}},
        )
        self._assert_code(
            E_PR_GATE_RULES,
            {"未知字段": {"canon_keywords": ["x"], "forbid_text": ["y"], "scope": "text", "oops": 1}},
        )
        self._assert_code(E_PR_GATE_RULES, {})
        self._assert_code(E_PR_GATE_RULES, [])


class TestGatePure(unittest.TestCase):
    """V2: check takes only a trace and a kernel, and is deterministic."""

    def test_signature_is_two_arguments(self) -> None:
        """V2: no store, path, clock or random source is accepted."""
        self.assertEqual(list(inspect.signature(check).parameters), ["trace", "kernel"])
        self.assertFalse(hasattr(gate_module, "utc_now"))

    def test_fake_kernel_is_enough(self) -> None:
        """V2: a duck-typed kernel without store/evidence still gets a verdict."""
        kernel = _fake_kernel((DIRECTIVE,))
        self.assertFalse(hasattr(kernel, "store"))
        self.assertFalse(hasattr(kernel, "evidence"))
        self.assertTrue(check(_text_trace(CLEAN_TEXT), kernel).allowed)
        self.assertFalse(check(_text_trace(BAD_TEXT), kernel).allowed)

    def test_hundred_runs_identical(self) -> None:
        """V2: the same kernel and trace always produce the same Verdict."""
        kernel = _fake_kernel((DIRECTIVE,))
        trace = _text_trace(BAD_TEXT)
        first = check(trace, kernel)
        same = sum(1 for _ in range(PURE_RUNS - 1) if check(trace, kernel) == first)
        self.assertEqual(same, PURE_RUNS - 1)
        self.assertEqual(first.rule, "禁称呼")
        self.assertEqual(first.segment_index, 0)
        print(f"V2 identical={same + 1}/{PURE_RUNS} rule={first.rule}")


class TestGateDecision(unittest.TestCase):
    """V3-V6: allow, refuse, data-driven rules and the no-canon case."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_gate_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "mem"
        init_store(self.store)
        append_event(self.store, "user", "今天天气不错", "2026-01-01T09:00:00Z")
        append_event(
            self.store, type="directive", kind="lock", text=DIRECTIVE, t=STAMP
        )
        self.kernel = compile_kernel(self.store, Policy(now=NOW))
        self.assertIn(DIRECTIVE, [entry.text for entry in self.kernel.canon])

    def test_gate_allows_clean_trace(self) -> None:
        """V3: a clean trace passes and the sink is called exactly once."""
        sink = _CountingSink()
        verdict = emit(_text_trace(CLEAN_TEXT), self.kernel, sink, store=self.store)
        self.assertTrue(verdict.allowed)
        self.assertIsNone(verdict.rule)
        self.assertEqual(len(sink.calls), 1)
        self.assertEqual(sink.calls[0].segments[0].value, CLEAN_TEXT)
        self.assertEqual(verify_path(self.store).events, 2)
        print(f"V3 allowed={verdict.allowed} sink_calls={len(sink.calls)}")

    def test_gate_refuses_and_records(self) -> None:
        """V4: a violating trace never reaches the sink, and becomes evidence."""
        trace = _text_trace(BAD_TEXT)
        sink = _CountingSink()
        before = verify_path(self.store).events
        verdict = emit(trace, self.kernel, sink, store=self.store)
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.rule, "禁称呼")
        self.assertEqual(verdict.segment_index, 0)
        self.assertTrue(verdict.detail)
        self.assertEqual(len(sink.calls), 0)
        after = verify_path(self.store).events
        self.assertEqual(after, before + 1)
        events = [
            json.loads(line)
            for line in (self.store / "evidence" / "seg-0001.jsonl")
            .read_text(encoding="utf-8").splitlines()
        ]
        refusal = events[-1]
        self.assertEqual(refusal["type"], "refusal")
        self.assertEqual(refusal["kind"], "gate")
        self.assertEqual(refusal["target"], "text")
        self.assertEqual(refusal["text"], "禁称呼")
        self.assertEqual(
            refusal["trace"],
            "sha256:" + hashlib.sha256(trace.to_bytes()).hexdigest(),
        )
        self.assertEqual(refusal["trace"], trace_digest(trace))
        self.assertEqual(verify_path(self.store).events, after)
        print(
            f"V4 allowed={verdict.allowed} sink_calls={len(sink.calls)} "
            f"events={before}->{after} verify=ok"
        )

    def test_gate_refuses_without_store(self) -> None:
        """V4: without a store the verdict is still returned, sink stays at 0."""
        sink = _CountingSink()
        verdict = emit(_text_trace(BAD_TEXT), self.kernel, sink, mode="both")
        self.assertFalse(verdict.allowed)
        self.assertEqual(len(sink.calls), 0)
        append_refusal(
            self.store, "action", "禁称呼", trace_digest(_text_trace(CLEAN_TEXT)), STAMP
        )
        self.assertEqual(verify_path(self.store).events, 3)

    def test_gate_rules_are_data(self) -> None:
        """V5: adding a forbidden word to the data changes the verdict."""
        calm = _text_trace("亲爱的，晚安")
        self.assertTrue(emit(calm, self.kernel, _CountingSink()).allowed)
        original = gate_module.DATA_FILE
        rules = json.loads(original.read_text(encoding="utf-8"))
        rules["禁新词"] = {
            "canon_keywords": ["叫我"],
            "forbid_text": ["亲爱的"],
            "scope": "text",
        }
        custom = self.root / "gate_rules.json"
        custom.write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
        try:
            gate_module.DATA_FILE = custom
            gate_module.load_gate_rules.cache_clear()
            verdict = check(calm, self.kernel)
        finally:
            gate_module.DATA_FILE = original
            gate_module.load_gate_rules.cache_clear()
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.rule, "禁新词")
        self.assertTrue(check(calm, self.kernel).allowed)
        print(f"V5 added_rule={verdict.rule} restored_allowed=True")

    def test_gate_no_canon_no_gate(self) -> None:
        """V6: a kernel without that constraint lets the same trace through."""
        sink = _CountingSink()
        without = _fake_kernel(("今晚十点睡",))
        verdict = emit(_text_trace(BAD_TEXT), without, sink)
        self.assertTrue(verdict.allowed)
        self.assertEqual(len(sink.calls), 1)
        self.assertTrue(check(_text_trace(BAD_TEXT), _fake_kernel(())).allowed)
        print(f"V6 no_canon_allowed={verdict.allowed} sink_calls={len(sink.calls)}")

    def test_refusal_rejects_bad_shape(self) -> None:
        """V4: refusal target and trace are validated at the evidence boundary."""
        bad_target = ("audio", "禁称呼", trace_digest(_text_trace(CLEAN_TEXT)))
        with self.assertRaises(JianError) as caught:
            append_refusal(self.store, *bad_target, t=STAMP)
        self.assertEqual(caught.exception.code, E_SCHEMA)
        with self.assertRaises(JianError) as caught:
            append_refusal(self.store, "text", "禁称呼", "sha256:ABC", t=STAMP)
        self.assertEqual(caught.exception.code, E_SCHEMA)


if __name__ == "__main__":
    unittest.main()
