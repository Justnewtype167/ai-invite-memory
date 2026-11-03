# -*- coding: utf-8 -*-
"""Sweep the four persona groups across many synthetic personas (M16 data run)."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from aiinvite.canonical import dumps
from aiinvite.capsule import init_store, append_payload_event, seal_store
from aiinvite.kernel.kernel import Policy
from aiinvite.pcs.judge import judge_reply
from aiinvite.pcs.probes import load_all_probes
from aiinvite.pcs.score import Reply
from aiinvite.persona import build_persona_view
from aiinvite.persona.view import _user_section
from aiinvite.persona.style_card import parse_style_card, record_style_card

import style_experiment as SE

CORPUS = ROOT / "corpus" / "personas.jsonl"
TRAITS = ROOT / "aiinvite/kernel" / "data" / "traits.json"
NOW = "2026-11-01T10:00:00+08:00"
GROUPS = ("A", "B", "C", "D")


def load_personas(limit: int) -> list[dict]:
    rows = []
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
        if len(rows) >= limit:
            break
    return rows


def build_store(root: pathlib.Path, persona: dict) -> pathlib.Path:
    store = root / "store"
    init_store(store)

    def add(text: str, stamp: str, *, type: str = "turn", kind: str | None = None) -> None:
        role = "user" if type == "turn" else None
        append_payload_event(store, "text", text, text.encode("utf-8"), role=role,
                             t=stamp, type=type, kind=kind)

    for index, utterance in enumerate(persona.get("sample_utterances", [])[:4]):
        add(str(utterance), f"2026-01-0{index + 1}T09:00:00Z")
    facts = persona.get("seed_facts", [])
    for index, fact in enumerate(facts[:3]):
        add(str(fact), f"2026-01-1{index}T09:00:00Z")
    for assertion in persona.get("assertions", [])[:2]:
        add(str(assertion), "2026-01-20T09:00:00Z", type="directive", kind="lock")

    vocabulary = json.loads(TRAITS.read_text(encoding="utf-8"))
    names = sorted(vocabulary)
    seed = int(hashlib.sha256(persona["id"].encode()).hexdigest()[:8], 16)
    picked = [names[seed % len(names)], names[(seed // 7) % len(names)]]
    for name in dict.fromkeys(picked):
        if "support" in vocabulary[name]["modes"]:
            add(name, "2026-01-21T09:00:00Z", type="directive", kind="trait")

    utterances = [str(u) for u in persona.get("sample_utterances", [])][:3]
    card = {
        "source": {"from_event": "ev_000001", "to_event": "ev_000004", "count": 4},
        "distilled_at": "2026-11-01T00:00:00Z",
        "model": "synthetic",
        "prompt_sha": "a" * 64,
        "rhythm": str(persona.get("speech", ""))[:60] or "短句为主",
        "address": "自称我；称呼按用户卡",
        "tics": [str(persona.get("speech", ""))[:8]] if persona.get("speech") else [],
        "examples": [u[:24] for u in utterances],
        "counter_examples": ["好的呢亲，很高兴为您服务哦"],
        "forbidden": [],
    }
    record_style_card(store, parse_style_card(dumps(card).decode("utf-8")))
    seal_store(store)
    return store


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="persona_sweep")
    parser.add_argument("--personas", type=int, default=100)
    parser.add_argument("--groups", nargs="+", choices=GROUPS + ("E",), default=list(GROUPS))
    parser.add_argument("--models", nargs="+", default=list(SE.DEFAULT_MODELS))
    parser.add_argument("--probes", type=int, default=3)
    parser.add_argument("--out", default=str(ROOT / "docs" / "results-persona-sweep.jsonl"))
    args = parser.parse_args(argv)

    all_probes = load_all_probes()
    personas = load_personas(args.personas)
    out_path = pathlib.Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    done = 0
    with out_path.open("w", encoding="utf-8") as handle:
        for persona in personas:
            seed = int(hashlib.sha256(persona["id"].encode()).hexdigest()[:8], 16)
            chosen = [all_probes[(seed + i * 7) % len(all_probes)] for i in range(args.probes)]
            root = pathlib.Path(tempfile.mkdtemp(prefix="sweep_"))
            try:
                store = build_store(root, persona)
                policy = Policy(now=NOW)
                for group in args.groups:
                    view = build_persona_view(store, policy=policy, mode="support")
                    if group == "E":
                        # E = bare kernel + user card only (separates the card from C).
                        base = SE.system_for("A", view)
                        body = _user_section(view.user_card) if view.user_card else ""
                        system = base if not body else base + "\n\n" + body
                    else:
                        system = SE.system_for(group, view)
                    verdicts = {}
                    tokens = 0
                    for model in args.models:
                        replies, spend = SE.collect(chosen, system, model)
                        tokens += spend
                        verdicts[model] = {
                            probe.probe_id: judge_reply(replies[probe.probe_id].text, probe.expect)
                            for probe in chosen
                        }
                    row = {
                        "persona": persona["id"],
                        "group": group,
                        "modes": {m: verdicts[m] for m in verdicts},
                        "tokens": tokens,
                    }
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    handle.flush()
                done += 1
                print(f"[{done}/{len(personas)}] {persona['id']} ok", flush=True)
            except Exception as error:  # noqa: BLE001 - a bad persona must not stop the sweep
                print(f"[{done+1}/{len(personas)}] {persona['id']} FAILED: {error}", flush=True)
            finally:
                shutil.rmtree(root, True)
    print(f"done: {done}/{len(personas)} -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())