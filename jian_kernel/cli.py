"""Command line entry points for the persona kernel (M4)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jian_kernel.compiler import compile_kernel
from jian_kernel.errors import KernelError
from jian_kernel.history import (
    diff_versions,
    history,
    record_kernel,
    verify_kernel,
)
from jian_kernel.kernel import Policy
from jian_kernel.proposer import record_proposal


def main(argv: list[str] | None = None) -> int:
    """Run one kernel command and return the process exit code."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "compile":
            policy = Policy(
                now=args.now,
                require_proposals=args.require_proposals,
                allow_fallback=args.allow_fallback,
            )
            kernel = compile_kernel(Path(args.store), policy)
            _emit({
                "canon": len(kernel.canon),
                "head": kernel.head,
                "kid": kernel.kid,
                "origin": kernel.origin,
                "rejected": kernel.rejected,
                "style": len(kernel.style),
            })
            return 0
        if args.command == "record":
            result = record_kernel(
                Path(args.store),
                Policy(now=args.now, require_proposals=args.require_proposals),
                args.force,
                allow_fallback=args.allow_fallback,
            )
            _emit({
                "delta": result.delta.to_payload(),
                "head": result.head,
                "healed": result.healed,
                "kid": result.kid,
                "origin": result.origin,
                "version": result.version,
            })
            return 0
        if args.command == "propose":
            event = record_proposal(
                Path(args.store), args.target, args.text, args.model,
                args.prompt_sha, args.t,
            )
            _emit({"event": event.event_id, "target": event.target})
            return 0
        if args.command == "history":
            for entry in history(Path(args.store)):
                _emit(entry.to_payload())
            return 0
        if args.command == "diff":
            payload = diff_versions(Path(args.store), args.a, args.b).to_payload()
            _emit(payload)
            return 0
        report = verify_kernel(Path(args.store))
        print(f"OK kid={report.kid} version={report.version} head={report.head}")
        return 0
    except KernelError as error:
        _emit({"error": error.code, "message": error.message})
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jian_kernel")
    commands = parser.add_subparsers(dest="command", required=True)
    compile_command = commands.add_parser("compile")
    compile_command.add_argument("store")
    compile_command.add_argument("--now", default=None)
    compile_command.add_argument("--require-proposals", action="store_true")
    compile_command.add_argument("--allow-fallback", action="store_true")
    record = commands.add_parser("record")
    record.add_argument("store")
    record.add_argument("--now", default=None)
    record.add_argument("--force", action="store_true")
    record.add_argument("--require-proposals", action="store_true")
    record.add_argument("--allow-fallback", action="store_true")
    propose = commands.add_parser("propose")
    propose.add_argument("store")
    propose.add_argument("--text", required=True)
    propose.add_argument("--model", required=True)
    propose.add_argument("--prompt-sha", required=True)
    propose.add_argument("--target", default="self.style")
    propose.add_argument("--t", default=None)
    for name in ("history", "verify"):
        command = commands.add_parser(name)
        command.add_argument("store")
    diff = commands.add_parser("diff")
    diff.add_argument("store")
    diff.add_argument("--a", type=int, required=True)
    diff.add_argument("--b", type=int, required=True)
    return parser


def _emit(payload: object) -> None:
    sys.stdout.write(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
