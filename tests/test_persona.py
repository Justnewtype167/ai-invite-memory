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
import pathlib
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from jian.canonical import dumps
from jian.capsule import append_event, append_refusal, init_store
from jian_kernel.compiler import compile_kernel
from jian_kernel.incremental import compile_kernel_incremental, reconcile
from jian_kernel.kernel import Policy

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


if __name__ == "__main__":
    unittest.main()
