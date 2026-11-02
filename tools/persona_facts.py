"""Measure user-fact recall for groups A (no card) and E (card only)."""
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

from jian_kernel.kernel import Policy
from jian_persona import build_persona_view
from jian_persona.view import _user_section

import persona_sweep as PS
import style_experiment as SE

NOW = "2026-11-01T10:00:00+08:00"


def name_of(persona: dict) -> str:
    """Return the persona name from its seed facts."""
    for fact in persona.get("seed_facts", []):
        if fact.startswith("名字："):
            return fact.split("：", 1)[1].split("；", 1)[0]
    return ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="persona_facts")
    parser.add_argument("--personas", type=int, default=50)
    parser.add_argument("--groups", nargs="+", default=["A", "E"])
    parser.add_argument("--models", nargs="+", default=["qwen3.5:9b", "glm4:9b"])
    parser.add_argument("--out", default=str(ROOT / "docs" / "results-persona-facts.jsonl"))
    args = parser.parse_args(argv)

    personas = PS.load_personas(args.personas)
    out = pathlib.Path(args.out)
    question = "我叫什么名字？只回答名字。"
    with out.open("w", encoding="utf-8") as handle:
        for index, persona in enumerate(personas, 1):
            name = name_of(persona)
            if not name:
                continue
            root = pathlib.Path(tempfile.mkdtemp(prefix="facts_"))
            try:
                store = PS.build_store(root, persona)
                view = build_persona_view(store, policy=Policy(now=NOW))
                for group in args.groups:
                    system = SE.system_for("A", view)
                    if group == "E" and view.user_card is not None:
                        body = _user_section(view.user_card)
                        system = system + "\n\n" + body if body else system
                    for model in args.models:
                        text = SE.call_ollama(question, system, model, 0, 42)
                        handle.write(json.dumps({
                            "persona": persona["id"], "group": group, "model": model,
                            "hit": name in text, "answer": name, "reply": text[:80],
                        }, ensure_ascii=False) + "\n")
                        handle.flush()
                print(f"[{index}/{len(personas)}] {persona['id']} ok", flush=True)
            finally:
                shutil.rmtree(root, True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
