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

import json
import os
import sys
import urllib.request

ENDPOINT = "http://127.0.0.1:11434/api/generate"
MODEL = "qwen3.5:9b"
QUANT = "Q4_K_M"
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


def call_ollama(prompt: str) -> str:
    """POST one non-streaming /api/generate request and return its text."""
    body = json.dumps({
        "keep_alive": KEEP_ALIVE,
        "model": MODEL,
        "options": {
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
            "seed": SEED,
            "temperature": TEMP_MILLI / 1000,
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


def _reply(target: str, evidence: str) -> dict[str, object]:
    text = call_ollama(build_prompt(target, evidence))
    reply: dict[str, object] = {
        "model": MODEL,
        "ok": True,
        "quant": QUANT,
        "seed": SEED,
        "temp_milli": TEMP_MILLI,
        "text": text,
    }
    weights_sha = os.environ.get("JIAN_WEIGHTS_SHA", "")
    if weights_sha:
        reply["weights_sha"] = weights_sha
    return reply


def main() -> int:
    """Read one request line, run one proposal, print one reply line."""
    try:
        request = json.loads(sys.stdin.buffer.readline().decode("utf-8"))
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        target = request.get("target")
        evidence = request.get("evidence")
        if not isinstance(target, str) or not isinstance(evidence, str):
            raise ValueError("request needs string target and evidence")
        reply = _reply(target, evidence)
    except Exception as exc:
        reply = {"code": "E_PROPOSER_FAILED", "message": str(exc), "ok": False}
    sys.stdout.buffer.write(
        json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
