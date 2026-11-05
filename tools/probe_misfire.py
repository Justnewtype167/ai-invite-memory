"""Measure the cost of a wrong clue: does a bad bridge pull in a stranger memory?

Builds a small store of clearly different memories, generates real clues for
each with the local model, then asks vague questions and counts how often a
memory that is NOT the target gets retrieved.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aiinvite.capsule import append_event, init_store, seal_store
from aiinvite.kernel.compiler import read_evidence
from aiinvite.recall.clue_store import ClueStore
from aiinvite.recall.index import build_index
from aiinvite.recall.retrieve import search
from aiinvite.demo.engine import make_rewriter

STAMP = "2026-09-01T09:00:00+08:00"
NOW = "2026-11-01T12:00:00+08:00"

MEMORIES = [
    "我的狗叫阿黄，它去年走了",
    "最近工作压力很大，天天加班到十一点",
    "我妈上个月住院了，我一直在医院陪着",
    "计划年底去云南旅行，还没订票",
    "上周和小林吵架了，到现在没说话",
    "最近在看房子，首付还差二十万",
    "上个月升职了，但是活更多了",
    "最近总是失眠，凌晨三点还醒着",
    "开始学吉他了，手指头很疼",
    "家里养了一只猫，叫团子",
    "下周二是我生日",
    "三年前和前任分手，到现在没再谈",
]

QUESTIONS = [
    ("我的狗叫阿黄，它去年走了", "那件让我特别难过的事"),
    ("最近工作压力很大，天天加班到十一点", "最近累得不行，你记得吗"),
    ("我妈上个月住院了，我一直在医院陪着", "家里老人身体的事"),
    ("计划年底去云南旅行，还没订票", "我说过要去哪儿玩来着"),
    ("上周和小林吵架了，到现在没说话", "跟人闹别扭的事"),
    ("最近在看房子，首付还差二十万", "那件要花很多钱的事"),
    ("上个月升职了，但是活更多了", "工作上有变化的事"),
    ("最近总是失眠，凌晨三点还醒着", "晚上睡不着的事"),
    ("开始学吉他了，手指头很疼", "我最近在学的东西"),
    ("家里养了一只猫，叫团子", "我养的那个小家伙"),
    ("下周二是我生日", "快到我什么日子了"),
    ("三年前和前任分手，到现在没再谈", "感情上的事"),
]


def run(model: str) -> int:
    root = pathlib.Path(tempfile.mkdtemp(prefix="misfire_"))
    store = root / "m"
    init_store(store)
    ids = {}
    for text in MEMORIES:
        event = append_event(store, "user", text, STAMP)
        ids[text] = event.id
    for index in range(20):
        append_event(store, "user", "第" + str(index) + "条无关闲聊", STAMP)
    seal_store(store)
    build_index(store)

    caller = make_rewriter(model, timeout=120)
    clues = ClueStore(store, caller=caller)
    events = read_evidence(store)
    for text in MEMORIES:
        clues.ensure(ids[text], text)
    pairs = clues.pairs()
    print("=== " + model + " ===")
    print("线索条数: " + str(len(pairs)) + "/" + str(len(MEMORIES)))
    for event_id, clue_text in pairs:
        print("   " + event_id + "  " + clue_text)

    hit_right = 0
    noise_total = 0
    returned_total = 0
    print()
    for target_text, question in QUESTIONS:
        target_id = ids[target_text]
        hits = search(store, question, k=5, now=NOW, clues=pairs)
        got = [hit.event_id for hit in hits]
        right = target_id in got
        if right:
            hit_right += 1
        noise = [event_id for event_id in got if event_id != target_id]
        noise_total += len(noise)
        returned_total += len(got)
        print("  问：" + question)
        print("    返回 " + str(len(got)) + " 条 | 命中目标:" + str(right)
              + " | 无关:" + str(len(noise)))

    print()
    print("不漏（命中目标）: " + str(hit_right) + "/" + str(len(QUESTIONS)))
    if returned_total:
        print("误召率: " + str(round(noise_total / returned_total, 3))
              + "（无关条数/返回总条数）")
    else:
        print("误召率: 无返回")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    return run(argv[0] if argv else "glm4:9b")


if __name__ == "__main__":
    raise SystemExit(main())
