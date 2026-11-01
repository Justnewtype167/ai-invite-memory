"""Command line entry points for the persona kernel (M4)."""

from __future__ import annotations

import argparse
import json
import os
import shlex
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
from jian_kernel.incremental import compile_kernel_incremental, reconcile
from jian_kernel.kernel import Policy
from jian_kernel.proposer import ingest_live, record_proposal


def main(argv: list[str] | None = None) -> int:
    """Run one kernel command and return the process exit code."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "compile":
            store = Path(args.store)
            failed = 0
            if args.proposer_cmd:
                outcome = ingest_live(
                    store,
                    shlex.split(args.proposer_cmd, posix=os.name != "nt"),
                    args.proposer_timeout,
                    args.strict_proposals,
                )
                failed = outcome.failed
                for event in outcome.recorded:
                    _emit({"event": event.event_id, "target": event.target})
                for message in outcome.errors:
                    sys.stderr.write(f"proposer fallback: {message}\n")
            policy = Policy(
                now=args.now,
                require_proposals=args.require_proposals,
                allow_fallback=args.allow_fallback,
                force_fallback=failed > 0,
            )
            compile_one = (
                compile_kernel_incremental if args.incremental else compile_kernel
            )
            kernel = compile_one(store, policy)
            _emit({
                "canon": len(kernel.canon),
                "head": kernel.head,
                "kid": kernel.kid,
                "models": list(kernel.models),
                "origin": kernel.origin,
                "proposals_failed": failed,
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
                args.prompt_sha, args.t, quant=args.quant,
                weights_sha=args.weights_sha, temp_milli=args.temp_milli,
                seed=args.seed,
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
        if args.command == "reconcile":
            report = reconcile(
                Path(args.store),
                Policy(
                    now=args.now,
                    require_proposals=args.require_proposals,
                    allow_fallback=args.allow_fallback,
                ),
            )
            _emit(report.to_payload())
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
    compile_command.add_argument("--proposer-cmd", default=None)
    compile_command.add_argument("--proposer-timeout", type=int, default=200)
    compile_command.add_argument("--strict-proposals", action="store_true")
    compile_command.add_argument("--incremental", action="store_true")
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
    propose.add_argument("--quant", default=None)
    propose.add_argument("--weights-sha", default=None)
    propose.add_argument("--temp-milli", type=int, default=None)
    propose.add_argument("--seed", type=int, default=None)
    for name in ("history", "verify"):
        command = commands.add_parser(name)
        command.add_argument("store")
    diff = commands.add_parser("diff")
    diff.add_argument("store")
    diff.add_argument("--a", type=int, required=True)
    diff.add_argument("--b", type=int, required=True)
    reconcile_command = commands.add_parser("reconcile")
    reconcile_command.add_argument("store")
    reconcile_command.add_argument("--now", default=None)
    reconcile_command.add_argument("--require-proposals", action="store_true")
    reconcile_command.add_argument("--allow-fallback", action="store_true")
    return parser


def _emit(payload: object) -> None:
    sys.stdout.write(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
