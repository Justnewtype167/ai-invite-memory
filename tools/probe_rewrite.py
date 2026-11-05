"""Probe: does the local model rewrite a vague question into useful recalls?

Run with a live Ollama; prints the real keywords and whether they recover the
memory. This is the evidence behind docs/RESULTS-rewrite.md.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.capsule import append_event, init_store, seal_store
from aiinvite.demo.engine import make_rewriter
from aiinvite.recall.index import build_index
from aiinvite.recall.retrieve import search

STAMP = "2026-09-01T09:00:00+08:00"
NOW = "2026-11-01T12:00:00+08:00"
MEMORY = "我的狗叫阿黄，它去年走了"
NOISE = 60

QUESTIONS = [
    "我的狗叫什么名字？",
    "阿黄是谁？",
    "我养的那只小动物现在怎样了",
    "你还记得我跟你提过的那件难过的事吗",
]


class Counter:
    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def __call__(self, prompt):
        self.calls += 1
        return self.inner(prompt)


def build_store() -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp(prefix="probe_rewrite_"))
    store = root / "m"
    init_store(store)
    append_event(store, "user", MEMORY, STAMP)
    for index in range(NOISE):
        append_event(store, "user", "第" + str(index) + "条闲聊，今天天气还行", STAMP)
    seal_store(store)
    build_index(store)
    return store


def run(model: str) -> int:
    store = build_store()
    rewriter = Counter(make_rewriter(model))
    print("=== " + model + " ===")
    for question in QUESTIONS:
        start = time.perf_counter()
        plain = search(store, question, k=5, now=NOW)
        hits = search(store, question, k=5, now=NOW, rewriter=rewriter)
        cost = time.perf_counter() - start
        found = "阿黄" in " ".join(hit.text for hit in hits)
        print("  问：" + question)
        print("    词法命中: " + str(len(plain)) + " | 重写后命中: " + str(len(hits))
              + " | 捞到记忆: " + str(found) + " | %.2fs" % cost)
        if rewriter.calls:
            print("    模型调用次数: " + str(rewriter.calls))
            rewriter.calls = 0
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    models = argv or ["glm4:9b"]
    for model in models:
        run(model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
