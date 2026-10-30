"""CLI: python -m jian_pcs.cli pcs --a a.jsonl --b b.jsonl."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jian_pcs.errors import PcsError
from jian_pcs.probes import load_probes
from jian_pcs.report import render_report
from jian_pcs.score import compute_pcs, load_replies


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, score two reply files and print the PCS report."""
    parser = argparse.ArgumentParser(prog="jian_pcs")
    subparsers = parser.add_subparsers(dest="command", required=True)
    pcs = subparsers.add_parser("pcs", help="score two reply files")
    pcs.add_argument("--a", required=True, help="reply JSONL for model a")
    pcs.add_argument("--b", required=True, help="reply JSONL for model b")
    pcs.add_argument("--probes", default=None, help="override probe JSONL")
    args = parser.parse_args(argv)
    try:
        probes = load_probes(None if args.probes is None else Path(args.probes))
        replies_a = load_replies(Path(args.a))
        replies_b = load_replies(Path(args.b))
        report = compute_pcs(probes, replies_a, replies_b)
    except PcsError as exc:
        sys.stderr.write(f"{exc.code}: {exc.message}\n")
        return 1
    sys.stdout.write(render_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
