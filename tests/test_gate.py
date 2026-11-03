"""M13 V1-V6: the actuation gate, the single emit path and refusal evidence.

Traces in this file always come from the real projectors. A gate decision is
about what would actually be emitted, so a hand-built trace proves nothing.
"""

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

from aiinvite.capsule import append_event, append_refusal, init_store, verify_path
from aiinvite.errors import E_SCHEMA, AiInviteError
from aiinvite.kernel.compiler import compile_kernel
from aiinvite.kernel.kernel import CanonEntry, Policy

import aiinvite.projection.gate as gate_module
from aiinvite.projection import (
    Trace,
    Verdict,
    check,
    emit,
    load_gate_rules,
    project_action,
    project_text,
    trace_digest,
)
from aiinvite.projection.errors import (
    E_PR_GATE_RULES,
    E_PR_GATE_SCOPE,
    ProjectionError,
)

NOW = "2026-10-29T10:00:00+08:00"
STAMP = "2026-10-29T09:00:00Z"
DIRECTIVE = "别叫我宝贝"
NOD_DIRECTIVE = "别复述"
PURE_RUNS = 100


def _fake_kernel(texts: tuple[str, ...]) -> SimpleNamespace:
    """Return a duck-typed kernel with canon entries but no store or clock."""
    canon = tuple(
        CanonEntry("directive", text, (f"ev_{index + 1:06d}",))
        for index, text in enumerate(texts)
    )
    return SimpleNamespace(
        kid="k" * 64, self_md="# Self\n- events: 3\n", canon=canon
    )


class _CountingSink:
    """A sink that records how many times it was called."""

    def __init__(self) -> None:
        self.calls: list[Trace] = []

    def __call__(self, trace: Trace) -> None:
        self.calls.append(trace)


class TestGateSchema(unittest.TestCase):
    """V1: Verdict fields and rule-data validation with fixed error codes."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_gate_schema_"))
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
        self.assertIn("禁称呼", [rule.name for rule in rules.rules])

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
        allow = _fake_kernel((DIRECTIVE,))
        refuse = _fake_kernel((NOD_DIRECTIVE,))
        self.assertFalse(hasattr(allow, "store"))
        self.assertFalse(hasattr(allow, "evidence"))
        self.assertTrue(check(project_text(allow), allow).allowed)
        self.assertFalse(check(project_action(refuse), refuse).allowed)

    def test_hundred_runs_identical(self) -> None:
        """V2: the same kernel and trace always produce the same Verdict."""
        kernel = _fake_kernel((NOD_DIRECTIVE,))
        trace = project_action(kernel)
        first = check(trace, kernel)
        same = sum(1 for _ in range(PURE_RUNS - 1) if check(trace, kernel) == first)
        self.assertEqual(same, PURE_RUNS - 1)
        self.assertEqual(first.rule, "不复述")
        self.assertEqual(first.segment_index, 0)
        print(f"V2 identical={same + 1}/{PURE_RUNS} rule={first.rule}")


class TestGateDecision(unittest.TestCase):
    """V3-V6: allow, refuse, data-driven rules and the no-canon case."""

    def setUp(self) -> None:
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_gate_"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.store = self.root / "mem"
        init_store(self.store)
        append_event(self.store, "user", "今天天气不错", "2026-01-01T09:00:00Z")
        append_event(
            self.store, type="directive", kind="lock", text=DIRECTIVE, t=STAMP
        )
        append_event(
            self.store, type="directive", kind="lock", text=NOD_DIRECTIVE, t=STAMP
        )
        self.kernel = compile_kernel(self.store, Policy(now=NOW))
        texts = [entry.text for entry in self.kernel.canon]
        self.assertIn(DIRECTIVE, texts)
        self.assertIn(NOD_DIRECTIVE, texts)

    def test_gate_allows_real_text_projection(self) -> None:
        """V3: text_v1 restates the constraint and is still allowed."""
        trace = project_text(self.kernel)
        self.assertTrue(any("宝贝" in segment.value for segment in trace.segments))
        self.assertEqual(trace.segments[0].role, "description")
        self.assertTrue(
            all(segment.role == "constraint" for segment in trace.segments[1:])
        )
        self.assertFalse(any(segment.role == "speech" for segment in trace.segments))
        sink = _CountingSink()
        verdict = emit(trace, self.kernel, sink, store=self.store)
        self.assertTrue(verdict.allowed)
        self.assertIsNone(verdict.rule)
        self.assertEqual(len(sink.calls), 1)
        self.assertEqual(verify_path(self.store).events, 3)
        print(
            f"V3 text_segments={len(trace.segments)} roles="
            f"{[segment.role for segment in trace.segments]} allowed={verdict.allowed}"
        )

    def test_gate_refuses_real_action_projection(self) -> None:
        """V4: a real action trace that violates is never sent and becomes evidence."""
        trace = project_action(self.kernel)
        self.assertEqual([segment.value for segment in trace.segments][:2], ["hold", "nod"])
        sink = _CountingSink()
        before = verify_path(self.store).events
        verdict = emit(trace, self.kernel, sink, store=self.store, mode="action")
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.rule, "不复述")
        self.assertEqual(verdict.segment_index, 1)
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
        self.assertEqual(refusal["target"], "action")
        self.assertEqual(refusal["text"], "不复述")
        self.assertEqual(
            refusal["trace"],
            "sha256:" + hashlib.sha256(trace.to_bytes()).hexdigest(),
        )
        self.assertEqual(refusal["trace"], trace_digest(trace))
        self.assertEqual(verify_path(self.store).events, after)
        print(
            f"V4 allowed={verdict.allowed} rule={verdict.rule} "
            f"index={verdict.segment_index} sink_calls={len(sink.calls)} "
            f"events={before}->{after} verify=ok"
        )

    def test_gate_refuses_without_store(self) -> None:
        """V4: without a store the verdict is still returned, sink stays at 0."""
        trace = project_action(self.kernel)
        sink = _CountingSink()
        verdict = emit(trace, self.kernel, sink, mode="both")
        self.assertFalse(verdict.allowed)
        self.assertEqual(len(sink.calls), 0)
        self.assertEqual(trace_digest(trace), trace_digest(project_action(self.kernel)))

    def test_gate_rules_are_data(self) -> None:
        """V5: adding a forbidden action to the data changes the verdict."""
        counting = _fake_kernel(("先复述",))
        base = check(project_action(counting), counting)
        self.assertEqual(list(project_action(counting).segments)[0].value, "nod")
        self.assertTrue(base.allowed)
        original = gate_module.DATA_FILE
        rules = json.loads(original.read_text(encoding="utf-8"))
        rules["禁点头"] = {
            "canon_keywords": ["复述"],
            "forbid_action": ["nod"],
            "scope": "action",
        }
        custom = self.root / "gate_rules.json"
        custom.write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
        try:
            gate_module.DATA_FILE = custom
            gate_module.load_gate_rules.cache_clear()
            verdict = check(project_action(counting), counting)
        finally:
            gate_module.DATA_FILE = original
            gate_module.load_gate_rules.cache_clear()
        self.assertFalse(verdict.allowed)
        self.assertEqual(verdict.rule, "禁点头")
        self.assertTrue(check(project_action(counting), counting).allowed)
        print(f"V5 added_rule={verdict.rule} restored_allowed=True")

    def test_gate_no_canon_no_gate(self) -> None:
        """V6: a kernel without that constraint lets the same real trace through."""
        trace = project_action(self.kernel)
        sink = _CountingSink()
        without = _fake_kernel(("今晚十点睡",))
        verdict = emit(trace, without, sink, mode="action")
        self.assertTrue(verdict.allowed)
        self.assertEqual(len(sink.calls), 1)
        self.assertTrue(check(trace, _fake_kernel(())).allowed)
        print(f"V6 no_canon_allowed={verdict.allowed} sink_calls={len(sink.calls)}")

    def test_refusal_rejects_bad_shape(self) -> None:
        """V4: refusal target and trace are validated at the evidence boundary."""
        digest = trace_digest(project_action(self.kernel))
        with self.assertRaises(AiInviteError) as caught:
            append_refusal(self.store, "audio", "禁称呼", digest, t=STAMP)
        self.assertEqual(caught.exception.code, E_SCHEMA)
        with self.assertRaises(AiInviteError) as caught:
            append_refusal(self.store, "text", "禁称呼", "sha256:ABC", t=STAMP)
        self.assertEqual(caught.exception.code, E_SCHEMA)


if __name__ == "__main__":
    unittest.main()
