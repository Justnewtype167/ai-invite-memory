# -*- coding: utf-8 -*-
"""Aggregate the persona sweep: per-group mean PCS with paired bootstrap CIs."""
from __future__ import annotations

import json
import pathlib
import random
import statistics as st

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATH = ROOT / "docs" / "results-persona-sweep.jsonl"
GROUPS = ("A", "B", "C", "D")


def load() -> dict[str, dict[str, dict]]:
    rows = [json.loads(line) for line in PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    table: dict[str, dict[str, dict]] = {}
    for row in rows:
        table.setdefault(row["group"], {})[row["persona"]] = row
    return table


def score(row: dict) -> tuple[float, float, float]:
    models = list(row["modes"])
    per_model = []
    for model in models:
        verdicts = row["modes"][model]
        per_model.append(sum(1 for v in verdicts.values() if v == "pass") / len(verdicts))
    ids = list(row["modes"][models[0]])
    agree = sum(1 for i in ids if all(row["modes"][m][i] == row["modes"][models[0]][i] for m in models)) / len(ids)
    pcs = agree * min(per_model)
    return per_model[0], per_model[1] if len(per_model) > 1 else per_model[0], agree * min(per_model)


def pcs_of(row: dict) -> float:
    return score(row)[2]


def main() -> None:
    table = load()
    personas = sorted(set.intersection(*(set(table[g]) for g in GROUPS if g in table)))
    print(f"小组齐全的人格数: {len(personas)}")
    for g in GROUPS:
        if g in table:
            print(f"  {g}: {len(table[g])} 条")
    print()

    print("| 组 | 人格数 | 平均 PCS | 中位 PCS | 平均 C(模型1) | 平均 C(模型2) | 平均 tokens |")
    print("|---|---|---|---|---|---|---|")
    means = {}
    for g in GROUPS:
        if g not in table:
            continue
        rows = [table[g][p] for p in personas]
        pcs = [pcs_of(r) for r in rows]
        c1 = [score(r)[0] for r in rows]
        c2 = [score(r)[1] for r in rows]
        tok = [r["tokens"] for r in rows]
        means[g] = pcs
        print(f"| {g} | {len(rows)} | {st.mean(pcs):.4f} | {st.median(pcs):.4f} | "
              f"{st.mean(c1):.4f} | {st.mean(c2):.4f} | {st.mean(tok):.0f} |")

    rng = random.Random(20261102)
    print()
    print("=== 配对差（同一人格，相对 A 组）===")
    for g in GROUPS[1:]:
        if g not in means or "A" not in means:
            continue
        deltas = [b - a for a, b in zip(means["A"], means[g])]
        boots = []
        for _ in range(4000):
            sample = [deltas[rng.randrange(len(deltas))] for _ in deltas]
            boots.append(st.mean(sample))
        boots.sort()
        lo = boots[int(0.025 * len(boots))]
        hi = boots[int(0.975 * len(boots))]
        wins = sum(1 for d in deltas if d > 0)
        print(f"  {g} - A: {st.mean(deltas):+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]  "
              f"提升人格数 {wins}/{len(deltas)}")

    print()
    print("=== 各组 PCS 的 95% CI（按人格重采样）===")
    for g in GROUPS:
        if g not in means:
            continue
        boots = []
        for _ in range(4000):
            sample = [means[g][rng.randrange(len(means[g]))] for _ in means[g]]
            boots.append(st.mean(sample))
        boots.sort()
        print(f"  {g}: {st.mean(means[g]):.4f}  [{boots[int(0.025*len(boots))]:.4f}, {boots[int(0.975*len(boots))]:.4f}]")


if __name__ == "__main__":
    main()
