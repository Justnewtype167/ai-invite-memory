"""Command line entry point for the Chinese rule layer (four commands)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

from aiinvite.cn.errors import CnError
from aiinvite.cn.kinship import parse_kinship
from aiinvite.cn.normalize import normalize
from aiinvite.cn.slang import availability, explain, lifespan
from aiinvite.cn.timex import parse_time


class _Parser(argparse.ArgumentParser):
    """Argument parser that exits with 1 (not 2) on usage errors."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n")
        raise SystemExit(1)


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="aiinvite.cn", description="Chinese rule layer (M2)")
    sub = parser.add_subparsers(dest="command", required=True)

    kinship = sub.add_parser("kinship", help="parse one kinship term")
    kinship.add_argument("term")

    timex = sub.add_parser("timex", help="parse one relative time expression")
    timex.add_argument("expr")
    timex.add_argument("--anchor", default=None)

    slang = sub.add_parser("slang", help="report slang availability")
    slang.add_argument("term")
    slang.add_argument("--on", default=None)

    norm = sub.add_parser("norm", help="normalize a text")
    norm.add_argument("text")
    return parser


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    """Run one command; return the process exit code."""
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "kinship":
            payload = parse_kinship(args.term).to_dict()
            print(_json(payload))
        elif args.command == "timex":
            print(_json(parse_time(args.expr, args.anchor).to_dict()))
        elif args.command == "slang":
            if args.on is None:
                payload = lifespan(args.term)
                print("未收录" if payload is None else _json(payload))
            else:
                try:
                    on = date.fromisoformat(args.on)
                except ValueError:
                    print(f"invalid date: {args.on}", file=sys.stderr)
                    return 1
                score = availability(args.term, on)
                print(_json({"term": args.term, "on": on.isoformat(),
                             "availability": score,
                             "explain": explain(args.term, on)}))
        elif args.command == "norm":
            print(normalize(args.text))
        else:
            return 1
    except CnError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
