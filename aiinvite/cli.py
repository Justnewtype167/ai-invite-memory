"""Command line interface with the seven M1 commands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .capsule import (
    append_event,
    export_capsule,
    import_capsule,
    init_store,
    inspect_capsule,
    seal_store,
    verify_path,
)
from .errors import E_ARG, E_IO, E_SCHEMA, AiInviteError


class _Parser(argparse.ArgumentParser):
    """Argument parser that reports bad usage as ``E_ARG`` with exit code 1."""

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        raise AiInviteError(E_ARG, message)


def build_parser() -> argparse.ArgumentParser:
    """Build the parser listing all seven commands."""
    parser = _Parser(prog="aiinvite", description="AI Invite M1 capsule toolkit")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p_init = sub.add_parser("init", help="create an empty memory store")
    p_init.add_argument("dir")
    p_init.set_defaults(handler=_cmd_init)

    p_append = sub.add_parser("append", help="append one evidence event")
    p_append.add_argument("dir")
    p_append.add_argument("--role", default=None, choices=["user", "assistant"])
    p_append.add_argument("--type", default=None)
    p_append.add_argument("--kind", default=None)
    p_append.add_argument("--text", required=True)
    p_append.add_argument("--t", default=None)
    p_append.set_defaults(handler=_cmd_append)

    p_seal = sub.add_parser("seal", help="freeze the store")
    p_seal.add_argument("dir")
    p_seal.set_defaults(handler=_cmd_seal)

    p_verify = sub.add_parser("verify", help="verify a store or a capsule")
    p_verify.add_argument("target")
    p_verify.set_defaults(handler=_cmd_verify)

    p_export = sub.add_parser("export", help="export a sealed store to .aiem")
    p_export.add_argument("dir")
    p_export.add_argument("out")
    p_export.set_defaults(handler=_cmd_export)

    p_import = sub.add_parser("import", help="import a capsule into a directory")
    p_import.add_argument("capsule")
    p_import.add_argument("dir")
    p_import.set_defaults(handler=_cmd_import)

    p_inspect = sub.add_parser("inspect", help="show capsule metadata")
    p_inspect.add_argument("capsule")
    p_inspect.set_defaults(handler=_cmd_inspect)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one command and return its process exit code."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return int(args.handler(args))
    except AiInviteError as exc:
        suffix = f" [event={exc.event_id}]" if exc.event_id else ""
        print(f"FAIL {exc.code} {exc.message}{suffix}", file=sys.stderr)
        return 1 if exc.code == E_ARG else 2
    except OSError as exc:
        print(f"FAIL {E_IO} {exc}", file=sys.stderr)
        return 2


def _cmd_init(args: argparse.Namespace) -> int:
    init_store(Path(args.dir))
    print(f"OK init {args.dir}")
    return 0


def _cmd_append(args: argparse.Namespace) -> int:
    if args.type is None:
        if args.role is None:
            raise AiInviteError(E_SCHEMA, "旧签名需要 --role")
        event = append_event(Path(args.dir), args.role, args.text, args.t)
    else:
        event = append_event(
            Path(args.dir), args.role, args.text, args.t,
            type=args.type, kind=args.kind,
        )
    print(f"OK append {event.id} seg={event.ep} type={event.type}")
    return 0


def _cmd_seal(args: argparse.Namespace) -> int:
    result = seal_store(Path(args.dir))
    print(_summary("seal", result))
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    result = verify_path(Path(args.target))
    print(
        f"OK events={result.events} segments={result.segments} "
        f"head={result.head[:8]} state={result.state}"
    )
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    result = export_capsule(Path(args.dir), Path(args.out))
    print(_summary("export", result))
    return 0


def _cmd_import(args: argparse.Namespace) -> int:
    result = import_capsule(Path(args.capsule), Path(args.dir))
    print(_summary("import", result))
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    info = inspect_capsule(Path(args.capsule))
    print(
        f"capsule schema={info.schema} version={info.version} created={info.created} "
        f"head={info.head} events={info.events} segments={info.segments} files={info.files}"
    )
    return 0


def _summary(label: str, result: object) -> str:
    events = getattr(result, "events")
    segments = getattr(result, "segments")
    head = getattr(result, "head")
    state = getattr(result, "state")
    return (
        f"OK {label} events={events} segments={segments} "
        f"head={head[:8]} state={state}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
