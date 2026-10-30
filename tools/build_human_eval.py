"""Build the human-evaluation sheet for the PCS judge (blind + key).

Samples 60 replies: every machine-judged ``fail`` (13) plus 47 ``pass``
items stratified by source. The blind sheet omits the machine verdict so the
human label is independent; the key file holds the mapping.

Usage:
    python tools/build_human_eval.py

"""

from __future__ import annotations

import csv
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jian_pcs.judge import judge_reply
from jian_pcs.probes import load_hard_probes, load_probes
from jian_pcs.score import load_replies

SEED = 20261030
PASS_QUOTA = {
    "qwen_base": 15,
    "glm_base": 15,
    "qwen_hi": 9,
    "qwen_hard": 8,
}


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
            })
    return items


def main() -> int:
    """Write the blind sheet, the key and a short README."""
    items = gather()
    fails = [item for item in items if item["machine"] == "fail"]
    passes = [item for item in items if item["machine"] == "pass"]
    rng = random.Random(SEED)

    picked: list[dict[str, object]] = list(fails)
    for source, quota in PASS_QUOTA.items():
        pool = [item for item in passes if item["source"] == source]
        rng.shuffle(pool)
        picked.extend(pool[:quota])
    rng.shuffle(picked)

    out_dir = ROOT / "human_eval"
    out_dir.mkdir(exist_ok=True)

    blind = out_dir / "blind.csv"
    with blind.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["编号", "规则", "输入", "模型回复", "我的判定（填 是 / 否 / 不确定）"])
        key: dict[str, object] = {}
        for index, item in enumerate(picked, start=1):
            label = f"H{index:02d}"
            writer.writerow([label, item["rule"], item["prompt"], item["reply"], ""])
            key[label] = item

    (out_dir / "key.json").write_text(
        json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8"
    )

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
    print(f"wrote {blind.relative_to(ROOT)}  rows={len(picked)}")
    print(f"wrote {(out_dir / 'key.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
