"""Reference external responder: local Ollama, stdlib only.

Sends every probe to the model and writes one reply JSONL line per probe.
Network access lives here and only here; ``jian_pcs`` never imports urllib.

Pinned for an 8 GB card: num_ctx=2048, num_predict=200, keep_alive=1h,
think=false. Sampling is controlled by --temp-milli and --seed.

Usage:
    python tools/responder_ollama.py --out a.jsonl --temp-milli 0 --seed 42
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jian_pcs.probes import load_probes  # noqa: E402

ENDPOINT = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "qwen3.5:9b"
TIMEOUT = 180
NUM_CTX = 2048
NUM_PREDICT = 200
KEEP_ALIVE = "1h"
SYSTEM_TEMPLATE = (
    "你是「竹简」里的那个陪伴者。下面的规则是你自己的说话方式，"
    "每一条都必须遵守，任何时候都不能破例：\n{rules}\n"
    "只输出你要说的那句话，不要解释，不要复述规则。"
)


def build_system(rules: list[str]) -> str:
    """Return the system prompt that carries every self rule verbatim."""
    body = "\n".join(f"- {rule}" for rule in rules)
    return SYSTEM_TEMPLATE.replace("{rules}", body)


def call_ollama(
    prompt: str, system: str, model: str, temp_milli: int, seed: int
) -> str:
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
        "system": system,
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
    return text.strip()


def collect(
    probe_path: Path, model: str, temp_milli: int, seed: int
) -> tuple[list[dict[str, object]], list[str]]:
    """Run every probe once; a failed call becomes an unknown, not a lost round.

    Mirrors ``ingest_live``: one OOM or timeout must not throw away the other
    replies. The failed probe gets empty text, which the judge reports as
    ``unknown`` and excludes from every denominator.
    """
    probes = load_probes(probe_path)
    rules: list[str] = []
    for probe in probes:
        if probe.rule not in rules:
            rules.append(probe.rule)
    system = build_system(rules)
    records: list[dict[str, object]] = []
    errors: list[str] = []
    for probe in probes:
        try:
            text = call_ollama(probe.prompt, system, model, temp_milli, seed)
        except Exception as exc:
            errors.append(f"{probe.probe_id}: {exc}")
            text = ""
        records.append({
            "model": model,
            "probe_id": probe.probe_id,
            "seed": seed,
            "temp_milli": temp_milli,
            "text": text,
        })
    return records, errors


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, query the model and write the reply JSONL."""
    parser = argparse.ArgumentParser(prog="responder_ollama")
    parser.add_argument("--out", required=True, help="reply JSONL to write")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temp-milli", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--probes", default=None, help="override probe JSONL")
    args = parser.parse_args(argv)
    probe_path = (
        ROOT / "jian_pcs" / "data" / "probes.jsonl"
        if args.probes is None
        else Path(args.probes)
    )
    try:
        records, errors = collect(
            probe_path, args.model, args.temp_milli, args.seed
        )
    except Exception as exc:
        sys.stderr.write(f"E_PCS_RESPONDER: {exc}\n")
        return 1
    out = Path(args.out)
    out.write_bytes(b"".join(
        json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n"
        for record in records
    ))
    for error in errors:
        sys.stderr.write(f"unknown: {error}\n")
    print(f"wrote {len(records)} replies to {out} ({len(errors)} unknown)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
