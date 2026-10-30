"""Build the human-evaluation sheet for the PCS judge (blind + key).

Default (v1): samples 60 replies with the old broad rules and writes
``human_eval/blind.csv``. With ``--rules-v2`` the sheet is rebuilt from the
executable rules in ``rules_v2.json``: the rule column carries the short
sentence plus the ``human`` definition, and R5 also lists its candidate
substrings, so the annotator can apply the rule mechanically.

Usage:
    python tools/build_human_eval.py
    python tools/build_human_eval.py --rules-v2

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

from jian_pcs.judge import judge_reply
from jian_pcs.probes import load_hard_probes, load_probes, load_rules_v2
from jian_pcs.score import load_replies

SEED = 20261030
PASS_QUOTA = {
    "qwen_base": 15,
    "glm_base": 15,
    "qwen_hi": 9,
    "qwen_hard": 8,
}
TOTAL_ROWS = 60


def gather() -> list[dict[str, object]]:
    """Return every judged item with its source, prompt and reply text."""
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
            verdict = judge_reply(reply.text, probe.expect)
            if verdict == "unknown":
                continue
            items.append({
                "source": source,
                "probe_id": probe.probe_id,
                "rule": probe.rule,
                "prompt": probe.prompt,
                "reply": reply.text,
                "machine": verdict,
                "must_contain_any": list(probe.expect.must_contain_any),
            })

    hard_path = ROOT / "m7_qwen.jsonl"
    if hard_path.exists():
        replies = load_replies(hard_path)
        for probe in hard:
            reply = replies.get(probe.probe_id)
            if reply is None:
                continue
            verdict = judge_reply(reply.final_text(), probe.expect)
            if verdict == "unknown":
                continue
            turns = reply.turns_replied or (reply.text,)
            items.append({
                "source": "qwen_hard",
                "probe_id": probe.probe_id,
                "rule": probe.rule,
                "prompt": " ／ ".join(turns[:-1]) if len(turns) > 1 else probe.prompt,
                "reply": turns[-1],
                "machine": verdict,
                "must_contain_any": list(probe.expect.must_contain_any),
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
    candidates = item.get("must_contain_any") or []
    if candidates:
        joined = "、".join(str(value) for value in candidates)
        label = f"{label}；候选子串：{joined}"
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
                item["prompt"],
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
    """Write the blind sheet and key; ``--rules-v2`` uses the v2 rule labels."""
    parser = argparse.ArgumentParser(prog="build_human_eval")
    parser.add_argument(
        "--rules-v2",
        action="store_true",
        help="use the executable rules_v2 definitions in the rule column",
    )
    args = parser.parse_args(argv)
    items = gather()
    fails = [item for item in items if item["machine"] == "fail"]
    passes = [item for item in items if item["machine"] == "pass"]
    out_dir = ROOT / "human_eval"
    out_dir.mkdir(exist_ok=True)

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
