"""Reference host adapter: wire a chat front-end to the Jian kernel (M17).

A host keeps five calls: on_user, on_assistant, prompt_for, reply and stats.
Everything else -- identity, persona, memory and the actuation gate -- lives
in the packages below. The adapter never calls a model: the host owns that.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jian.capsule import append_event, init_store, utc_now, verify_path
from jian_kernel.compiler import compile_kernel
from jian_kernel.kernel import Policy
from jian_persona import build_persona_view
from jian_persona.view import _user_section
from jian_pcs.probes import load_rules_v2
from jian_projection import emit as gate_emit
from jian_projection.trace import Segment, Trace
from jian_recall.index import build_index, index_status
from jian_recall.stream import StreamSession

RULE_HEADER = "## behavior rules"
CARD_HEADER = "## who you both are"
CONTEXT_HEADER = "## recent and recalled memory"
PERSONA_HEADER = "## persona"
INPUT_HEADER = "## this turn"
NEWLINE = chr(10)


class HostSession:
    """One conversation over one store, with a fixed reference time."""

    def __init__(self, store, model, budget=4096, now=None):
        self.store = pathlib.Path(store)
        self.model = model
        self.budget = budget
        self.now = now or utc_now()
        if not (self.store / "evidence").is_dir():
            init_store(self.store)
        self._stream = StreamSession(self.store, budget, now=self.now)
        self._counter = {"turns": 0, "refused": 0, "prompts": 0}

    def _ensure_index(self):
        """Build the derived index once; it never holds truth."""
        try:
            stale = index_status(self.store).stale
        except Exception:
            build_index(self.store)
            return
        if stale:
            build_index(self.store)

    def on_user(self, text, t):
        """Append the user turn to evidence."""
        append_event(self.store, "user", text, t)
        self._counter["turns"] += 1

    def on_assistant(self, text, t):
        """Append the assistant turn to evidence."""
        append_event(self.store, "assistant", text, t)
        self._counter["turns"] += 1

    def prompt_for(self, user_text):
        """Return the exact prompt this turn should send to the model."""
        self._counter["prompts"] += 1
        pieces = []
        rules = load_rules_v2()
        rule_lines = NEWLINE.join("- " + r.text for r in rules)
        pieces.append(RULE_HEADER + NEWLINE + rule_lines)
        view = build_persona_view(self.store, policy=Policy(now=self.now))
        if view.user_card is not None:
            body = _user_section(view.user_card)
            if body:
                pieces.append(CARD_HEADER + NEWLINE + body)
        self._ensure_index()
        context = self._stream.context(user_text)
        lines = [item.text for item in context.items if getattr(item, "text", "")]
        if lines:
            pieces.append(CONTEXT_HEADER + NEWLINE + NEWLINE.join(lines))
        if view.self_md.strip():
            pieces.append(PERSONA_HEADER + NEWLINE + view.self_md.strip())
        pieces.append(INPUT_HEADER + NEWLINE + user_text)
        return (NEWLINE * 2).join(pieces)

    def stats(self):
        """Return the counters this session has accumulated."""
        return dict(self._counter)

    def reply(self, text, t):
        """Gate the reply, then either record it or record the refusal."""
        kernel = compile_kernel(self.store, Policy(now=self.now))
        trace = Trace(
            kid=kernel.kid,
            projector="text_v1",
            segments=(Segment(kind="text", value=text, dur_ms=None),),
        )

        def sink(_trace):
            self.on_assistant(text, t)

        verdict = gate_emit(trace, kernel, sink, store=self.store, mode="text", t=t)
        if not verdict.allowed:
            self._counter["refused"] += 1
        return verdict


def _demo(store, say, model):
    session = HostSession(store, model)
    session.on_user(say, utc_now())
    print(session.prompt_for(say))
    print()
    print("--- stats ---")
    print(session.stats())
    verify_path(store)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="host_adapter")
    parser.add_argument("--store", required=True)
    parser.add_argument("--say", default="")
    parser.add_argument("--model", default="qwen3.5:9b")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.dry_run:
        parser.error("only --dry-run is implemented; the host owns model calls")
    return _demo(pathlib.Path(args.store), args.say or "hello", args.model)


if __name__ == "__main__":
    raise SystemExit(main())
