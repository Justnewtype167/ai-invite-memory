"""Reference host adapter: wire a chat front-end to the Jian kernel (M17).

A host keeps five calls: on_user, on_assistant, prompt_for, reply and stats.
Everything else -- identity, persona, memory and the actuation gate -- lives
in the packages below. The adapter never calls a model: the host owns that.

Budget rules (fixed after the M17 audit):

* ``budget`` is the budget for the WHOLE prompt, not just the memory block;
* the user input is truncated before any memory is dropped;
* an empty store degrades to rules + input instead of raising.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jian.capsule import append_event, init_store, utc_now, verify_path
from jian.errors import JianError
from jian_kernel.compiler import compile_kernel
from jian_kernel.errors import KernelError
from jian_kernel.kernel import Policy
from jian_persona import build_persona_view
from jian_pcs.probes import load_rules_v2
from jian_projection import emit as gate_emit
from jian_projection.trace import Segment, Trace
from jian_recall.errors import RecallError
from jian_recall.index import build_index, index_status
from jian_recall.stream import StreamSession
from jian_recall.tokenizer import estimate_tokens

NEWLINE = chr(10)
RULE_HEADER = "## behavior rules"
CARD_HEADER = "## who you both are"
CONTEXT_HEADER = "## recent and recalled memory"
PERSONA_HEADER = "## persona"
INPUT_HEADER = "## this turn"
EMPTY_NOTE = "(no memory yet)"
MIN_CONTEXT = 256
INPUT_RESERVE = 64


class HostSession:
    """One conversation over one store, with a fixed reference time."""

    def __init__(self, store, model, budget=4096, now=None):
        self.store = pathlib.Path(store)
        self.model = model
        self.budget = budget
        self.now = now or utc_now()
        if not (self.store / "evidence").is_dir():
            init_store(self.store)
        self._counter = {"turns": 0, "refused": 0, "prompts": 0}

    # -- writes --------------------------------------------------------
    def on_user(self, text, t):
        """Append the user turn to evidence."""
        append_event(self.store, "user", text, t)
        self._counter["turns"] += 1

    def on_assistant(self, text, t):
        """Append an assistant turn directly. Never use this for gated output.

        Kept for host-side imports and replays; every live reply must go
        through ``reply`` so the actuation gate runs.
        """
        append_event(self.store, "assistant", text, t)
        self._counter["turns"] += 1

    # -- read-only -----------------------------------------------------
    def _ensure_index(self):
        """Build the derived index when it is missing or stale."""
        try:
            stale = index_status(self.store).stale
        except RecallError:
            build_index(self.store)
            return
        if stale:
            build_index(self.store)

    def _rules(self):
        rules = load_rules_v2()
        return RULE_HEADER + NEWLINE + NEWLINE.join("- " + r.text for r in rules)

    def _card_and_persona(self):
        """Return (card_block, persona_block); both empty when nothing is known."""
        try:
            view = build_persona_view(self.store, policy=Policy(now=self.now))
        except (KernelError, JianError):
            return "", "", None
        card = ""
        if view.user_card is not None:
            body = view.user_card.text().strip()
            if body and body != "- none":
                card = CARD_HEADER + NEWLINE + body
        persona = ""
        if view.self_md.strip():
            persona = PERSONA_HEADER + NEWLINE + view.self_md.strip()
        return card, persona, view

    def _fit_input(self, text, allowance):
        """Truncate the user input so it costs at most ``allowance`` tokens."""
        if allowance <= 0:
            return ""
        if estimate_tokens(text) <= allowance:
            return text
        keep = max(1, len(text) // 2)
        while keep > 1 and estimate_tokens(text[:keep]) > allowance:
            keep //= 2
        return text[:keep]

    def prompt_for(self, user_text):
        """Return the exact prompt this turn should send to the model."""
        if estimate_tokens(user_text) > self.budget - INPUT_RESERVE:
            user_text = self._fit_input(user_text, self.budget - INPUT_RESERVE)
        rules = self._rules()
        card, persona, view = self._card_and_persona()
        fixed = [rules]
        if card:
            fixed.append(card)
        if persona:
            fixed.append(persona)
        input_block = INPUT_HEADER + NEWLINE + user_text
        overhead = sum(estimate_tokens(part) for part in fixed) + estimate_tokens(input_block)
        room = self.budget - overhead
        context = ""
        if view is not None and room >= MIN_CONTEXT:
            try:
                self._ensure_index()
                session = StreamSession(self.store, room, now=self.now)
                assembled = session.context(user_text)
                lines = [item.text for item in assembled.items if getattr(item, "text", "")]
                if lines:
                    context = CONTEXT_HEADER + NEWLINE + NEWLINE.join(lines)
            except (RecallError, KernelError, JianError):
                context = ""
        pieces = [rules]
        if card:
            pieces.append(card)
        if context:
            pieces.append(context)
        elif view is not None:
            pieces.append(CONTEXT_HEADER + NEWLINE + EMPTY_NOTE)
        if persona:
            pieces.append(persona)
        pieces.append(input_block)
        prompt = (NEWLINE * 2).join(pieces)
        if estimate_tokens(prompt) > self.budget:
            prompt = self._shrink(prompt, user_text)
        self._counter["prompts"] += 1
        return prompt

    def _shrink(self, prompt, user_text):
        """Last resort: drop the context block and re-fit the input."""
        rules = self._rules()
        room = self.budget - estimate_tokens(rules) - INPUT_RESERVE
        text = self._fit_input(user_text, max(1, room))
        return (NEWLINE * 2).join([rules, INPUT_HEADER + NEWLINE + text])

    def stats(self):
        """Return the counters this session has accumulated."""
        return dict(self._counter)

    # -- gated write ---------------------------------------------------
    def reply(self, text, t):
        """Gate the reply, then either record it or record the refusal."""
        kernel = compile_kernel(self.store, Policy(now=self.now))
        trace = Trace(
            kid=kernel.kid,
            projector="text_v1",
            segments=(Segment(kind="text", value=text, dur_ms=None),),
        )

        def sink(_trace):
            append_event(self.store, "assistant", text, t)
            self._counter["turns"] += 1

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
