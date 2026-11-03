"""R1-R6: incremental compilation equals full compilation and is reconcilable."""

from __future__ import annotations

import json
import pathlib
import random
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import kn_fixtures

from aiinvite.kernel.cli import main
from aiinvite.kernel.compiler import compile_kernel
from aiinvite.kernel.errors import E_KN_DRIFT, E_KN_SNAPSHOT, E_KN_STALE, KernelError
from aiinvite.kernel.incremental import compile_kernel_incremental, reconcile
from aiinvite.kernel.kernel import Policy
from aiinvite.kernel.proposer import record_proposal
from aiinvite.kernel.snapshot import SNAPSHOT_FILE, digest_of

NOW = "2026-10-29T10:00:00+08:00"
GROUPS = 20
PROMPT_SHA = "ab12cd34"

TURNS = (
    "今天天气不错",
    "妈妈下周三做手术",
    "聊聊工作吧",
    "昨天去了公园",
    "下个月要搬家",
    "周末一起吃饭",
    "爸爸最近很忙",
    "姐姐发了照片",
)
PROMISES = (
    "我答应你下次一定早点睡",
    "保证下周给你打电话",
    "说好周末一起去看电影",
)
DONES = ("已完成那个事", "已办好了", "我做到了")
DIRECTIVES = ("以后不许半夜打电话", "说话短一点", "别老夸我", "别叫我宝贝")
FEEDBACKS = (("你做得不对", "correction"), ("这次很好", "praise"))
MILESTONES = ("我们第一次见面", "一起过的第一个生日")
PROPOSALS = (
    ("self.style", "说话时慢一点", "m1"),
    ("self.conduct", "别老追问", "m2"),
    ("self.style", "先复述再回答", "m1"),
)

Action = tuple


def _plan(rng: random.Random) -> list[Action]:
    """Return one deterministic random sequence of typed actions."""
    cursor = datetime(2026, 2, 10, 9, 0, 0)
    plan: list[Action] = []
    for _ in range(rng.randint(8, 14)):
        cursor += timedelta(days=rng.choice((1, 1, 2, 3, 5, 40, 41, 70)))
        stamp = cursor.strftime("%Y-%m-%dT%H:%M:%SZ")
        choice = rng.choices(
            ("turn", "promise", "done", "directive", "feedback", "milestone",
             "proposal"),
            weights=(4, 2, 2, 2, 2, 1, 3),
        )[0]
        if choice == "turn":
            plan.append(("event", (stamp, rng.choice(TURNS), "turn", None)))
        elif choice == "promise":
            plan.append(("event", (stamp, rng.choice(PROMISES), "turn", None)))
        elif choice == "done":
            plan.append(("event", (stamp, rng.choice(DONES), "turn", None)))
        elif choice == "directive":
            plan.append(
                ("event", (stamp, rng.choice(DIRECTIVES), "directive", "lock"))
            )
        elif choice == "feedback":
            text, kind = rng.choice(FEEDBACKS)
            plan.append(("event", (stamp, text, "feedback", kind)))
        elif choice == "milestone":
            plan.append(("event", (stamp, rng.choice(MILESTONES), "milestone", None)))
        else:
            target, text, model = rng.choice(PROPOSALS)
            plan.append(("proposal", target, text, model, stamp))
    return plan


def _apply(root: pathlib.Path, action: Action) -> None:
    """Append one planned action to the evidence chain."""
    if action[0] == "event":
        kn_fixtures.append_events(root, [action[1]])
        return
    _, target, text, model, stamp = action
    record_proposal(root, target, text, model, PROMPT_SHA, stamp)


def _rewrite(path: pathlib.Path, data: dict, recalc: bool) -> None:
    """Write a tampered snapshot, optionally restoring a valid digest."""
    if recalc:
        body = {key: value for key, value in data.items() if key != "digest"}
        data["digest"] = digest_of(body)
    path.write_bytes(json.dumps(data, ensure_ascii=False).encode("utf-8"))


class TestIncremental(unittest.TestCase):
    def _store(self) -> pathlib.Path:
        root = pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_m12_"))
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def test_incremental_equals_full(self) -> None:
        """R1: twenty random sequences match the full compile after every add."""
        policy = Policy(now=NOW)
        runs = 0
        for group in range(GROUPS):
            root = self._store()
            rng = random.Random(1200 + group)
            kn_fixtures.write_store(root, kn_fixtures.chat_turns(10))
            counter: list[int] = []
            first = compile_kernel_incremental(root, policy, counter)
            expected = compile_kernel(root, policy)
            self.assertEqual(counter, [10])
            self.assertEqual(first.kid, expected.kid)
            self.assertEqual(first.files(1), expected.files(1))
            for action in _plan(rng):
                _apply(root, action)
                counter.clear()
                incremental = compile_kernel_incremental(root, policy, counter)
                expected = compile_kernel(root, policy)
                label = f"group {group} action {action}"
                self.assertEqual(counter, [1], label)
                self.assertEqual(incremental.kid, expected.kid, label)
                self.assertEqual(incremental.files(1), expected.files(1), label)
                runs += 1
        print(f"R1 groups={GROUPS} incremental_runs={runs}")

    def test_policy_change_forces_full(self) -> None:
        """R2: a different policy clock invalidates the snapshot, no error."""
        root = self._store()
        kn_fixtures.write_store(root, kn_fixtures.chat_turns(12))
        early = Policy(now=NOW)
        counter: list[int] = []
        first = compile_kernel_incremental(root, early, counter)
        self.assertEqual(counter, [12])
        late = Policy(now="2027-01-15T10:00:00+08:00")
        counter.clear()
        again = compile_kernel_incremental(root, late, counter)
        expected = compile_kernel(root, late)
        print(f"R2 early={first.kid[:12]} late={again.kid[:12]}")
        self.assertEqual(counter, [12])
        self.assertEqual(again.kid, expected.kid)
        self.assertEqual(again.files(1), expected.files(1))
        self.assertNotEqual(first.kid, again.kid)

    def test_snapshot_discardable(self) -> None:
        """R3: deleting store/kernel degenerates to a full compile, same kid."""
        root = self._store()
        kn_fixtures.write_store(root, kn_fixtures.chat_turns(15))
        policy = Policy(now=NOW)
        counter: list[int] = []
        first = compile_kernel_incremental(root, policy, counter)
        self.assertEqual(counter, [15])
        shutil.rmtree(root / "kernel")
        counter.clear()
        again = compile_kernel_incremental(root, policy, counter)
        print(f"R3 kid={again.kid[:12]} discarded=True")
        self.assertEqual(counter, [15])
        self.assertEqual(again.kid, first.kid)
        self.assertEqual(again.files(1), first.files(1))

    def test_snapshot_tamper(self) -> None:
        """R4: edited fields and a false digest are refused, stale head too."""
        root = self._store()
        kn_fixtures.write_store(root, kn_fixtures.chat_turns(12))
        policy = Policy(now=NOW)
        compile_kernel_incremental(root, policy)
        path = root / "kernel" / SNAPSHOT_FILE
        original = path.read_bytes()

        def edit(data: dict) -> None:
            data["kid"] = "0" * 64

        def drop(data: dict) -> None:
            data.pop("self_md")

        def stale(data: dict) -> None:
            data["head"] = "ev_999999"

        def false_digest(data: dict) -> None:
            data["digest"] = "sha256:" + "0" * 64

        cases = (
            ("kid edited", edit, False, E_KN_SNAPSHOT),
            ("digest edited", false_digest, False, E_KN_SNAPSHOT),
            ("field dropped", drop, True, E_KN_SNAPSHOT),
            ("head stale", stale, True, E_KN_STALE),
        )
        for label, mutate, recalc, code in cases:
            data = json.loads(original.decode("utf-8"))
            mutate(data)
            _rewrite(path, data, recalc)
            with self.assertRaises(KernelError) as caught:
                compile_kernel_incremental(root, policy)
            print(f"R4 {label} -> {caught.exception.code}")
            self.assertEqual(caught.exception.code, code, label)
        path.write_bytes(original)

    def test_work_is_delta_sized(self) -> None:
        """R5: work is counted in events, never in wall-clock time."""
        root = self._store()
        kn_fixtures.write_store(root, kn_fixtures.chat_turns(20))
        policy = Policy(now=NOW)
        counter: list[int] = []
        compile_kernel_incremental(root, policy, counter)
        self.assertEqual(counter, [20])
        for index in range(4):
            kn_fixtures.append_events(
                root,
                [(f"2026-03-{index + 1:02d}T09:00:00Z",
                  f"追加{index}", "turn", None)],
            )
            counter.clear()
            compile_kernel_incremental(root, policy, counter)
            self.assertEqual(counter, [1])
        counter.clear()
        compile_kernel_incremental(root, policy, counter)
        print("R5 full=20 delta=1,1,1,1 idle=0")
        self.assertEqual(counter, [0])

    def test_reconcile_detects_drift(self) -> None:
        """R6: a hand-written kid is caught by reconcile and by the CLI."""
        root = self._store()
        kn_fixtures.write_store(root, kn_fixtures.chat_turns(12))
        policy = Policy(now=NOW)
        kernel = compile_kernel_incremental(root, policy)
        report = reconcile(root, policy)
        print(f"R6 reconcile={report.to_payload()['status']} kid={report.kid[:12]}")
        self.assertEqual(report.kid, kernel.kid)
        self.assertEqual(report.to_payload()["status"], "ok")
        self.assertEqual(main(["reconcile", str(root), "--now", NOW]), 0)

        path = root / "kernel" / SNAPSHOT_FILE
        data = json.loads(path.read_bytes().decode("utf-8"))
        data["kid"] = "0" * 64
        _rewrite(path, data, True)

        with self.assertRaises(KernelError) as caught:
            reconcile(root, policy)
        print(f"R6 wrong kid -> {caught.exception.code}")
        self.assertEqual(caught.exception.code, E_KN_DRIFT)
        self.assertEqual(main(["reconcile", str(root), "--now", NOW]), 1)


if __name__ == "__main__":
    unittest.main()
