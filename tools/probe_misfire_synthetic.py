"""What happens when a clue is WRONG? Deterministic, no model needed.

The model's clue quality is a separate question; this probe fixes that and asks
the safety question: if a bridge label is wrong, how much does it pollute recall?
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.capsule import append_event, init_store, seal_store
from aiinvite.recall.index import build_index
from aiinvite.recall.retrieve import search

STAMP = "2026-09-01T09:00:00+08:00"
NOW = "2026-11-01T12:00:00+08:00"

SOURCES = [
    ("狗", "我的狗叫阿黄，它去年走了"),
    ("天气", "今天天气还行，就是有点闷"),
    ("工作", "最近工作压力很大，天天加班"),
    ("旅行", "计划年底去云南旅行"),
]

QUESTION = "那件让我特别难过的事"


def build():
    root = pathlib.Path(tempfile.mkdtemp(prefix="misfire_syn_"))
    store = root / "m"
    init_store(store)
    ids = {}
    for label, text in SOURCES:
        ids[label] = append_event(store, "user", text, STAMP).id
    for index in range(20):
        append_event(store, "user", "第" + str(index) + "条无关闲聊", STAMP)
    seal_store(store)
    build_index(store)
    return store, ids


def labels(store):
    """Return a label -> event id map by rebuilding the same order."""
    from aiinvite.kernel.compiler import read_evidence
    events = [event for event in read_evidence(store)]
    order = {}
    for event in events:
        for label, text in SOURCES:
            if event.text == text:
                order[label] = event.event_id
    return order


def main() -> int:
    store, ids = build()
    query = QUESTION

    print("=== 对照：线索全对 ===")
    correct = [(ids["狗"], "阿黄 狗 走了", "悲伤")]
    hits = search(store, query, k=5, now=NOW, clues=correct)
    print("  返回 " + str(len(hits)) + " 条: " + str([h.event_id for h in hits]))

    print()
    print("=== 污染：给每条记忆都贴上「悲伤」（错的也算）===")
    wrong = [(ids[label], "", "悲伤") for label, _ in SOURCES]
    hits = search(store, query, k=5, now=NOW, clues=wrong)
    print("  返回 " + str(len(hits)) + " 条: " + str([h.event_id for h in hits]))
    polluted = [h.event_id for h in hits if h.event_id != ids["狗"]]
    print("  被错线索拉进来的无关记忆: " + str(len(polluted)))

    print()
    print("=== 部分污染：两条记忆共享同一个桥（不过阈值）===")
    partial = [(ids["狗"], "阿黄 狗", "悲伤"), (ids["天气"], "", "悲伤")]
    hits = search(store, query, k=5, now=NOW, clues=partial)
    print("  返回 " + str(len(hits)) + " 条: " + str([h.event_id for h in hits]))
    print("  无关: " + str([h.event_id for h in hits if h.event_id != ids["狗"]]))

    print()
    print("=== 对照：完全无线索（词法基线）===")
    hits = search(store, query, k=5, now=NOW)
    print("  返回 " + str(len(hits)) + " 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
