"""Command line entry points for the recall layer (M3)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from jian_recall.assemble import assemble
from jian_recall.errors import RecallError
from jian_recall.index import IndexStatus, build_index, index_status, update_index


def main(argv: list[str] | None = None) -> int:
    """Run one recall command and return the process exit code."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            return _print_status(build_index(Path(args.store)))
        if args.command == "update":
            return _print_status(update_index(Path(args.store)))
        if args.command == "status":
            return _print_status(index_status(Path(args.store)))
        start = time.perf_counter()
        context = assemble(
            Path(args.store), args.query, args.budget, args.now
        )
        took_ms = int(round((time.perf_counter() - start) * 1000))
        payload = context.to_dict()
        payload["stats"] = {"candidates": context.candidates, "took_ms": took_ms}
        _emit(payload)
        return 0
    except RecallError as error:
        _emit({"error": error.code, "message": error.message})
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jian_recall")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "update", "status"):
        command = commands.add_parser(name)
        command.add_argument("store")
    ask = commands.add_parser("ask")
    ask.add_argument("store")
    ask.add_argument("query")
    ask.add_argument("--budget", type=int, default=4096)
    ask.add_argument("--now", default=None)
    return parser


def _print_status(status: IndexStatus) -> int:
    _emit(
        {
            "events_indexed": status.events_indexed,
            "lsn": status.lsn,
            "stale": status.stale,
        }
    )
    return 0


def _emit(payload: object) -> None:
    sys.stdout.write(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
