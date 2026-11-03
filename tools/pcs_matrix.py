"""Run the PCS experiment matrix and print one table (paper figure 1).

For every model: collect replies to the probe set, then score every pair.
Optionally also compare proposal-driven kernels so content identity (kid)
and behavioural identity (PCS) can be reported side by side.

Network lives in the two adapters; this script only orchestrates them.

Usage:
    python tools/pcs_matrix.py --models qwen3.5:9b glm4:9b
"""

from __future__ import annotations

import argparse
import itertools
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from aiinvite.pcs.probes import load_probes
from aiinvite.pcs.report import render_report
from aiinvite.pcs.score import compute_pcs, load_replies


def collect(model: str, out_dir: pathlib.Path, temp_milli: int, seed: int) -> pathlib.Path:
    """Run the responder for one model and return the reply file path."""
    target = out_dir / f"replies_{model.replace(chr(58), chr(95))}.jsonl"
    command = [
        sys.executable, str(ROOT / "tools" / "responder_ollama.py"),
        "--model", model,
        "--out", str(target),
        "--temp-milli", str(temp_milli),
        "--seed", str(seed),
    ]
    print(f"  collect {model} -> {target.name}")
    subprocess.run(command, cwd=str(ROOT), check=True, timeout=3600)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pcs_matrix")
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--temp-milli", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default="pcs_out")
    parser.add_argument("--reuse", action="store_true", help="reuse existing reply files")
    args = parser.parse_args(argv)

    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    probes = load_probes()

    files: dict[str, pathlib.Path] = {}
    for model in args.models:
        path = out_dir / f"replies_{model.replace(chr(58), chr(95))}.jsonl"
        if not (args.reuse and path.exists()):
            path = collect(model, out_dir, args.temp_milli, args.seed)
        files[model] = path

    replies = {model: load_replies(path) for model, path in files.items()}

    print()
    print(f"probes={len(probes)}  temp_milli={args.temp_milli}  seed={args.seed}")
    print()
    header = "pair".ljust(26) + "C(a)".rjust(7) + "C(b)".rjust(7) + "A".rjust(7) + "PCS".rjust(7)
    print(header)
    print("-" * len(header))
    rows = []
    for a, b in itertools.combinations_with_replacement(args.models, 2):
        report = compute_pcs(probes, replies[a], replies[b])
        pair = f"{a} vs {b}" if a != b else f"{a} (self)"
        print(
            pair.ljust(26)
            + f"{report.model_a.c:.2f}".rjust(7)
            + f"{report.model_b.c:.2f}".rjust(7)
            + f"{report.agreement:.2f}".rjust(7)
            + f"{report.pcs:.2f}".rjust(7)
        )
        rows.append({
            "a": a, "b": b,
            "c_a": report.model_a.c, "c_b": report.model_b.c,
            "agreement": report.agreement, "pcs": report.pcs,
            "skipped": report.skipped,
            "per_rule": [
                {"rule": r.rule, "probes": r.probes, "c_a": r.c_a, "c_b": r.c_b, "a": r.a}
                for r in report.per_rule
            ],
        })

    payload = {
        "models": args.models,
        "temp_milli": args.temp_milli,
        "seed": args.seed,
        "probes": len(probes),
        "pairs": rows,
    }
    out_file = out_dir / "matrix.json"
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print(f"wrote {out_file.relative_to(ROOT)}")
    print()
    first = rows[0]
    detail = compute_pcs(probes, replies[first["a"]], replies[first["b"]])
    print(render_report(detail))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
