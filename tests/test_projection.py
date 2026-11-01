"""M11 T1-T6: trace contract, two projectors and the four invariants."""

from __future__ import annotations

import hashlib
import inspect
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from jian_kernel.compiler import compile_kernel
from jian_kernel.kernel import CanonEntry, Policy

import jian_projection.action as action_module
from jian_projection import (
    ACTION_WHITELIST,
    PROJECTORS,
    ProjectionError,
    Segment,
    Trace,
    load_action_map,
    project,
    project_action,
    project_text,
)
from jian_projection.errors import (
    E_PR_BAD_DURATION,
    E_PR_EMPTY,
    E_PR_MISSING_KID,
    E_PR_SCHEMA,
    E_PR_UNKNOWN_ACTION,
    E_PR_UNKNOWN_PROJECTOR,
)

NOW = "2026-10-29T10:00:00+08:00"
ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNS = 100
RULE_KEYS = ("不主动联系", "先复述", "不评价")
RULE_TEXTS = ("不主动联系", "先复述对方的话", "不评价对错")


def _fake_kernel(canon: tuple[CanonEntry, ...] = ()) -> SimpleNamespace:
    """Return a duck-typed kernel with no store, path or evidence attribute."""
    return SimpleNamespace(
        kid="k" * 64,
        self_md="# Self\n- events: 3\n",
        canon=canon,
    )


class TestTraceSchema(unittest.TestCase):
    def assert_code(self, code: str, func, *args, **kwargs) -> None:
        with self.assertRaises(ProjectionError) as caught:
            func(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_segment_schema(self) -> None:
        """T1: illegal kind, unknown action and bad durations report E_PR_*."""
        self.assert_code(E_PR_SCHEMA, Segment, "audio", "x", None)
        self.assert_code(E_PR_SCHEMA, Segment, "text", "x", 100)
        self.assert_code(E_PR_SCHEMA, Segment, "action", 7, 100)
        self.assert_code(E_PR_UNKNOWN_ACTION, Segment, "action", "wave", 100)
        self.assert_code(E_PR_BAD_DURATION, Segment, "action", "nod", None)
        self.assert_code(E_PR_BAD_DURATION, Segment, "wait", "", None)
        self.assert_code(E_PR_BAD_DURATION, Segment, "wait", "", 0)
        self.assert_code(E_PR_BAD_DURATION, Segment, "wait", "", 60001)
        self.assert_code(E_PR_BAD_DURATION, Segment, "wait", "", True)

    def test_trace_schema(self) -> None:
        """T1: missing kid, empty segments and unknown projector are rejected."""
        self.assert_code(E_PR_MISSING_KID, Trace, "", "text_v1", ())
        self.assert_code(E_PR_EMPTY, Trace, "kid", "text_v1", ())
        self.assert_code(
            E_PR_UNKNOWN_PROJECTOR,
            Trace,
            "kid",
            "audio_v1",
            (Segment("text", "x", None),),
        )
        self.assert_code(E_PR_SCHEMA, Trace, "kid", "text_v1", ("x",))
        self.assert_code(
            E_PR_SCHEMA,
            Trace,
            "kid",
            "text_v1",
            [Segment("text", "x", None)],
        )
        self.assert_code(E_PR_UNKNOWN_PROJECTOR, project, _fake_kernel(), "video_v1")

    def test_trace_serialization(self) -> None:
        """T1: a valid trace serializes to canonical JSON with no floats."""
        trace = Trace(
            "kid",
            "action_v1",
            (Segment("action", "nod", 600), Segment("wait", "", 800)),
        )
        payload = trace.to_payload()
        self.assertEqual(sorted(payload), ["kid", "projector", "segments"])
        self.assertEqual(payload["segments"][0], {"dur_ms": 600, "kind": "action", "value": "nod"})
        self.assertEqual(
            trace.to_bytes(),
            b'{"kid":"kid","projector":"action_v1","segments":['
            b'{"dur_ms":600,"kind":"action","value":"nod"},'
            b'{"dur_ms":800,"kind":"wait","value":""}]}',
        )


class TestProjectionInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = pathlib.Path(tempfile.mkdtemp(prefix="jian_pr_"))
        cls.addClassCleanup(shutil.rmtree, cls.root, True)
        events = [
            ("2026-01-01T09:00:00Z", "今天天气不错", "turn", None),
            ("2026-01-02T09:00:00Z", RULE_TEXTS[0], "directive", "lock"),
            ("2026-01-03T09:00:00Z", RULE_TEXTS[1], "directive", "lock"),
            ("2026-01-04T09:00:00Z", RULE_TEXTS[2], "directive", "lock"),
        ]
        kn_fixtures.write_store(cls.root, events)
        cls.kernel = compile_kernel(cls.root, Policy(now=NOW))

    def test_projection_pure(self) -> None:
        """T2: projectors take only a kernel object and never a store."""
        names = list(inspect.signature(project).parameters)
        self.assertEqual(names, ["kernel", "projector"])
        self.assertEqual(list(inspect.signature(project_text).parameters), ["kernel"])
        self.assertEqual(list(inspect.signature(project_action).parameters), ["kernel"])
        fake = _fake_kernel((CanonEntry("directive", RULE_TEXTS[1], ("ev_000003",)),))
        self.assertFalse(hasattr(fake, "store"))
        self.assertFalse(hasattr(fake, "evidence"))
        text_trace = project(fake, "text_v1")
        action_trace = project(fake, "action_v1")
        self.assertEqual(text_trace.kid, fake.kid)
        self.assertEqual(action_trace.kid, fake.kid)
        self.assertTrue(text_trace.segments)
        self.assertTrue(action_trace.segments)

    def test_kid_unchanged(self) -> None:
        """T3: projecting never changes kernel.kid and both traces carry it."""
        before = self.kernel.kid
        text_trace = project(self.kernel, "text_v1")
        action_trace = project(self.kernel, "action_v1")
        self.assertEqual(self.kernel.kid, before)
        self.assertEqual(text_trace.kid, before)
        self.assertEqual(action_trace.kid, before)

    def test_determinism(self) -> None:
        """T4: 100 projections are byte-identical, in and across processes."""
        first = {
            name: project(self.kernel, name).to_bytes() for name in PROJECTORS
        }
        identical = 0
        for _ in range(RUNS - 1):
            current = {
                name: project(self.kernel, name).to_bytes() for name in PROJECTORS
            }
            if current == first:
                identical += 1
        self.assertEqual(identical, RUNS - 1)
        cross = self._subprocess_text_bytes()
        self.assertEqual(cross, first["text_v1"].hex())
        print(
            f"T4 identical={identical + 1}/{RUNS} "
            f"text_sha={hashlib.sha256(first['text_v1']).hexdigest()[:12]} "
            f"action_sha={hashlib.sha256(first['action_v1']).hexdigest()[:12]}"
        )

    def _subprocess_text_bytes(self) -> str:
        """Compile and project in a fresh interpreter; return hex bytes."""
        code = (
            "import sys\n"
            "from pathlib import Path\n"
            "from jian_kernel.compiler import compile_kernel\n"
            "from jian_kernel.kernel import Policy\n"
            "from jian_projection import project\n"
            "kernel = compile_kernel(Path(sys.argv[1]), Policy(now=sys.argv[2]))\n"
            "sys.stdout.write(project(kernel, 'text_v1').to_bytes().hex())\n"
        )
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        env["PYTHONPATH"] = str(ROOT)
        completed = subprocess.run(
            [sys.executable, "-c", code, str(self.root), NOW],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout.strip()

    def test_two_forms_differ(self) -> None:
        """T5: two projectors differ in segments while sharing one kid."""
        text_trace = project(self.kernel, "text_v1")
        action_trace = project(self.kernel, "action_v1")
        self.assertNotEqual(text_trace.segments, action_trace.segments)
        self.assertEqual(text_trace.kid, action_trace.kid)
        self.assertEqual(text_trace.projector, "text_v1")
        self.assertEqual(action_trace.projector, "action_v1")
        self.assertNotEqual(text_trace.to_bytes(), action_trace.to_bytes())
        print(
            f"T5 kid={self.kernel.kid[:12]} text_segments={len(text_trace.segments)} "
            f"action_segments={len(action_trace.segments)}"
        )


class TestActionMap(unittest.TestCase):
    def test_action_map(self) -> None:
        """T6: every mapped action is legal and every rule projects."""
        mapping = load_action_map()
        self.assertEqual(action_module.DATA_FILE.name, "action_map.json")
        self.assertEqual([rule for rule, _ in mapping], list(RULE_KEYS))
        for rule, segments in mapping:
            self.assertTrue(segments)
            for segment in segments:
                self.assertIn(segment.kind, ("action", "wait"))
                if segment.kind == "action":
                    self.assertIn(segment.value, ACTION_WHITELIST)
                self.assertIsNotNone(segment.dur_ms)
        for rule, segments in mapping:
            kernel = _fake_kernel((CanonEntry("directive", rule, ("ev_1",)),))
            trace = project_action(kernel)
            self.assertEqual(trace.segments, segments)

    def test_unmatched_rule_is_ignored(self) -> None:
        """T6: a canon entry with no mapped rule is skipped without error."""
        kernel = _fake_kernel(
            (
                CanonEntry("directive", "今天天气不错", ("ev_1",)),
                CanonEntry("directive", RULE_TEXTS[1], ("ev_2",)),
            )
        )
        trace = project_action(kernel)
        expected = dict(load_action_map())[RULE_KEYS[1]]
        self.assertEqual(trace.segments, expected)


if __name__ == "__main__":
    unittest.main()
