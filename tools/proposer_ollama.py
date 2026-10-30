"""Reference external proposer: local Ollama, stdlib only.

One JSON line on stdin, one JSON line on stdout. Network access lives here
and only here; the kernel never imports urllib or socket.

Pinned for an 8 GB card: num_ctx=2048, num_predict=200, keep_alive=1h,
temperature=0.0, seed=42, think=false.

Usage:
    echo '{"target":"self.conduct","evidence":"...","prompt_sha":"..."}' \
        | python tools/proposer_ollama.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

ENDPOINT = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "qwen3.5:9b"
DEFAULT_QUANT = ""
TEMP_MILLI = 0
SEED = 42
TIMEOUT = 180
# An 8 GB card intermittently OOMs on the default 4096 context. 2048 is the
# ceiling that survives repeated runs; 200 output tokens are more than a
# 40-character rule needs. Keep the model resident so reloading cannot OOM.
NUM_CTX = 2048
NUM_PREDICT = 200
KEEP_ALIVE = "1h"
PROMPT_TEMPLATE = (
    "你在帮一个 AI 伙伴修订「{style|conduct}」。根据下面这段真实对话，"
    "写一条具体、可执行的要求。\n"
    "要求：\n"
    "- 不超过 40 个字\n"
    "- 不许用形容词堆砌（温柔、体贴、善解人意这类一律不许）\n"
    "- 要写成行为规则，能照着判断「做到了没有」\n"
    "- 只输出这一条，不要解释\n"
    "\n"
    "对话：\n"
    "{evidence}"
)


def build_prompt(target: str, evidence: str) -> str:
    """Return the frozen prompt template filled for one target."""
    label = "style" if target.rsplit(".", 1)[-1] == "style" else "conduct"
    return PROMPT_TEMPLATE.replace("{style|conduct}", label).replace(
        "{evidence}", evidence
    )


def call_ollama(prompt: str, model: str, temp_milli: int, seed: int) -> str:
    """POST one non-streaming /api/generate request and return its text."""
    body = json.dumps({
        "keep_alive": KEEP_ALIVE,
        "model": model,
        "options": {
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
            "seed": seed,
            "temperature": temp_milli / 1000,
        },
        "prompt": prompt,
        "stream": False,
        "think": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    text = payload.get("response")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("ollama returned an empty response")
    return text.strip()[:500]


def _reply(
    target: str,
    evidence: str,
    model: str,
    quant: str,
    temp_milli: int,
    seed: int,
) -> dict[str, object]:
    text = call_ollama(build_prompt(target, evidence), model, temp_milli, seed)
    reply: dict[str, object] = {
        "model": model,
        "ok": True,
        "seed": seed,
        "temp_milli": temp_milli,
        "text": text,
    }
    if quant:
        reply["quant"] = quant
    weights_sha = os.environ.get("JIAN_WEIGHTS_SHA", "")
    if weights_sha:
        reply["weights_sha"] = weights_sha
    return reply


def main(argv: list[str] | None = None) -> int:
    """Read one request line, run one proposal, print one reply line."""
    parser = argparse.ArgumentParser(prog="proposer_ollama")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--quant", default=DEFAULT_QUANT)
    parser.add_argument("--temp-milli", type=int, default=TEMP_MILLI)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)
    try:
        request = json.loads(sys.stdin.buffer.readline().decode("utf-8"))
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        target = request.get("target")
        evidence = request.get("evidence")
        if not isinstance(target, str) or not isinstance(evidence, str):
            raise ValueError("request needs string target and evidence")
        model = request.get("model") or args.model
        if not isinstance(model, str) or not model:
            raise ValueError("model must be a non-empty string")
        reply = _reply(
            target, evidence, model, args.quant, args.temp_milli, args.seed
        )
    except Exception as exc:
        reply = {"code": "E_PROPOSER_FAILED", "message": str(exc), "ok": False}
    sys.stdout.buffer.write(
        json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
