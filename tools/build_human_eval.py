"""Build the human-evaluation sheets for the PCS judge (blind + key).

Default (v1): samples 60 replies with the old broad rules and writes
``human_eval/blind.csv``. With ``--rules-v2`` the sheet is rebuilt from the
executable rules in ``rules_v2.json``: the rule column carries the short
sentence plus the ``human`` definition, and R5 also names the source
sentence it must echo, so the annotator can apply the rule mechanically.
With ``--holdout`` the frozen 60-row held-out sheet is written from the
``s2`` replies; every row is excluded from the tuning key by
``(source, probe_id)``.

Usage:
    python tools/build_human_eval.py
    python tools/build_human_eval.py --rules-v2
    python tools/build_human_eval.py --holdout

"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jian_pcs.judge import UNKNOWN, judge_reply
from jian_pcs.probes import Probe, load_hard_probes, load_probes, load_rules_v2
from jian_pcs.score import load_replies

SEED = 20261030
HOLDOUT_ROWS = 60
HOLDOUT_SOURCES = (
    ("qwen_s2", "replies_qwen3.5_9b_s2.jsonl"),
    ("glm_s2", "replies_glm4_9b_s2.jsonl"),
)
PASS_QUOTA = {
    "qwen_base": 15,
    "glm_base": 15,
    "qwen_hi": 9,
    "qwen_hard": 8,
}
TOTAL_ROWS = 60


def dialogue_input(probe: Probe) -> str:
    """Render the full user dialogue; the last line is the turn being answered.

    A multi-turn probe keeps every user turn, one speaker-labelled line each,
    so the annotator can see which sentence the reply must echo.
    """
    turns = probe.turns if probe.turns else (probe.prompt,)
    return "\n".join(f"用户：{turn}" for turn in turns)


def gather() -> list[dict[str, object]]:
    """Return every judged item with its source, full input and reply text."""
    base = load_probes()
    hard = load_hard_probes()
    items: list[dict[str, object]] = []

    for source, probes, path in (
        ("qwen_base", base, ROOT / "pcs_out" / "replies_qwen3.5_9b.jsonl"),
        ("glm_base", base, ROOT / "pcs_out" / "replies_glm4_9b.jsonl"),
        ("qwen_hi", base, ROOT / "c.jsonl"),
    ):
        if not path.exists():
            continue
        replies = load_replies(path)
        for probe in probes:
            reply = replies.get(probe.probe_id)
            if reply is None:
                continue
            verdict = judge_reply(reply.final_text(), probe.expect)
            if verdict == UNKNOWN:
                continue
            items.append({
                "source": source,
                "probe_id": probe.probe_id,
                "rule": probe.rule,
                "input": dialogue_input(probe),
                "reply": reply.final_text(),
                "machine": verdict,
                "echo_source": probe.expect.echo_source,
            })

    hard_path = ROOT / "m7_qwen.jsonl"
    if hard_path.exists():
        replies = load_replies(hard_path)
        for probe in hard:
            reply = replies.get(probe.probe_id)
            if reply is None:
                continue
            verdict = judge_reply(reply.final_text(), probe.expect)
            if verdict == UNKNOWN:
                continue
            items.append({
                "source": "qwen_hard",
                "probe_id": probe.probe_id,
                "rule": probe.rule,
                "input": dialogue_input(probe),
                "reply": reply.final_text(),
                "machine": verdict,
                "echo_source": probe.expect.echo_source,
            })
    return items


def _v2_pick(items: list[dict[str, object]]) -> list[dict[str, object]]:
    """Keep every failed item, then fill the remainder with passes.

    The pass rows are spread over the four sources in proportion to their
    pool size, using largest remainders so the total is exactly 60 whenever
    the data allows it.
    """
    fails = [item for item in items if item["machine"] == "fail"]
    passes = [item for item in items if item["machine"] == "pass"]
    rng = random.Random(SEED)
    if len(fails) >= TOTAL_ROWS:
        rng.shuffle(fails)
        return fails[:TOTAL_ROWS]
    wanted = TOTAL_ROWS - len(fails)
    sources = [source for source in PASS_QUOTA]
    pool_size = {
        source: sum(1 for item in passes if item["source"] == source)
        for source in sources
    }
    total_pass = sum(pool_size.values())
    quotas: dict[str, int] = {}
    remainders: list[tuple[float, str]] = []
    for source in sources:
        exact = wanted * pool_size[source] / total_pass if total_pass else 0.0
        quotas[source] = int(exact)
        remainders.append((exact - int(exact), source))
    left = wanted - sum(quotas.values())
    for _, source in sorted(remainders, reverse=True):
        if left <= 0:
            break
        if quotas[source] < pool_size[source]:
            quotas[source] += 1
            left -= 1
    picked: list[dict[str, object]] = list(fails)
    for source in sources:
        pool = [item for item in passes if item["source"] == source]
        rng.shuffle(pool)
        picked.extend(pool[: quotas[source]])
    rng.shuffle(picked)
    return picked


def _tuning_keys() -> set[tuple[str, str]]:
    """Return every ``(source, probe_id)`` already used by the tuning sheet."""
    path = ROOT / "human_eval" / "key_v2.json"
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        (str(item["source"]), str(item["probe_id"]))
        for item in data.values()
        if isinstance(item, dict) and "source" in item and "probe_id" in item
    }


def build_holdout() -> list[dict[str, object]]:
    """Return the held-out rows whose keys never appear in the tuning sheet.

    The holdout is sampled from a second run (``s2``) of the 30 base probes,
    so every ``(source, probe_id)`` differs from the tuning set by
    construction. Rows are emitted in probe order, qwen first.
    """
    tuning = _tuning_keys()
    probes = load_probes()
    items: list[dict[str, object]] = []
    for source, name in HOLDOUT_SOURCES:
        path = ROOT / "pcs_out" / name
        if not path.exists():
            raise ValueError(f"缺少回复文件：{path}")
        replies = load_replies(path)
        for probe in probes:
            reply = replies.get(probe.probe_id)
            if reply is None:
                raise ValueError(f"{source} 缺回复：{probe.probe_id}")
            text = reply.final_text()
            verdict = judge_reply(text, probe.expect)
            if verdict == UNKNOWN:
                raise ValueError(f"{source} 的 {probe.probe_id} 回复为空")
            if (source, probe.probe_id) in tuning:
                continue
            items.append({
                "source": source,
                "probe_id": probe.probe_id,
                "rule": probe.rule,
                "input": dialogue_input(probe),
                "reply": text,
                "machine": verdict,
                "echo_source": probe.expect.echo_source,
            })
    return items


def _rule_labels() -> dict[str, str]:
    """Return one mechanical rule label per rule id, human definition included."""
    labels: dict[str, str] = {}
    for rule in load_rules_v2():
        labels[rule.rule_id] = f"{rule.text}（判定：{rule.human}）"
    return labels


def _label(item: dict[str, object], labels: dict[str, str] | None) -> str:
    if labels is None:
        return str(item["rule"])
    label = labels[str(item["rule"])]
    source = str(item.get("echo_source") or "")
    if source:
        label = f"{label}；复述对象：{source}"
    return label


def _write_csv(
    path: pathlib.Path,
    picked: list[dict[str, object]],
    labels: dict[str, str] | None,
) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["编号", "规则", "输入", "模型回复", "我的判定（填 是 / 否 / 不确定）"])
        for index, item in enumerate(picked, start=1):
            row_label = f"H{index:02d}"
            writer.writerow([
                row_label,
                _label(item, labels),
                item["input"],
                item["reply"],
                "",
            ])


def _write_key(path: pathlib.Path, picked: list[dict[str, object]]) -> None:
    key = {
        f"H{index:02d}": item
        for index, item in enumerate(picked, start=1)
    }
    path.write_text(
        json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    """Write the blind or held-out sheet; ``--holdout`` uses the s2 replies."""
    parser = argparse.ArgumentParser(prog="build_human_eval")
    parser.add_argument(
        "--rules-v2",
        action="store_true",
        help="use the executable rules_v2 definitions in the rule column",
    )
    parser.add_argument(
        "--holdout",
        action="store_true",
        help="write the frozen 60-row held-out sheet, disjoint from the tuning key",
    )
    args = parser.parse_args(argv)
    out_dir = ROOT / "human_eval"
    out_dir.mkdir(exist_ok=True)

    if args.holdout:
        rows = build_holdout()
        if len(rows) != HOLDOUT_ROWS:
            raise SystemExit(f"holdout rows={len(rows)}，必须是 {HOLDOUT_ROWS}")
        labels = _rule_labels()
        holdout = out_dir / "holdout.csv"
        _write_csv(holdout, rows, labels)
        _write_key(out_dir / "holdout_key.json", rows)
        print(f"wrote {holdout.relative_to(ROOT)}  rows={len(rows)}")
        print(f"wrote {(out_dir / 'holdout_key.json').relative_to(ROOT)}")
        return 0

    items = gather()
    fails = [item for item in items if item["machine"] == "fail"]
    passes = [item for item in items if item["machine"] == "pass"]

    if args.rules_v2:
        labels = _rule_labels()
        picked = _v2_pick(items)
        blind = out_dir / "blind_v2.csv"
        _write_csv(blind, picked, labels)
        _write_key(out_dir / "key_v2.json", picked)
        print(f"items={len(items)} fails={len(fails)} passes={len(passes)}")
        print(f"wrote {blind.relative_to(ROOT)}  rows={len(picked)}")
        print(f"wrote {(out_dir / 'key_v2.json').relative_to(ROOT)}")
        return 0

    picked = _v2_pick(items)
    _write_csv(out_dir / "blind.csv", picked, None)
    _write_key(out_dir / "key.json", picked)
    readme = out_dir / "README.md"
    readme.write_text(
        "# 人工判定表\n\n"
        "`blind.csv` 用 Excel 打开（已带 BOM，不会乱码）。\n\n"
        "只需看「规则 / 输入 / 模型回复」三列，回答一个问题是或否：\n"
        "**这条回复符合那条规则吗？** 拿不准就填「不确定」。\n\n"
        "不要看 `key.json`——那是机器判定，看了会影响你的判断。\n\n"
        f"共 {len(picked)} 条（其中机器判不过 {len(fails)} 条，判过 {len(picked) - len(fails)} 条）。\n"
        "填完告诉我，我来算你与判定器的一致率。\n",
        encoding="utf-8",
    )
    print(f"items={len(items)} fails={len(fails)} passes={len(passes)}")
    print(f"wrote {(out_dir / 'blind.csv').relative_to(ROOT)}  rows={len(picked)}")
    print(f"wrote {(out_dir / 'key.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
