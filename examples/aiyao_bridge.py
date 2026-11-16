"""Reference wiring for 爱邀 on Tencent Cloud: library embed, no sidecar.

The chat path is three calls; the console path is two. Everything else —
tokens, HTTPS, the user table, the model call — stays in 爱邀's own backend.

    chat:  turn(key, user_text) -> prompt -> [your model] -> reply(key, text)
    GM:    view(key) to read; rule(key, text) to write

Why a file and not a framework: the engine already ships the service. What
used to take a design conversation is only the *order* of these calls and what
to do when one of them errors. Copy this file, adjust three constants, done.

Key mapping. One key is one memory (one evidence chain, one persona):

    one companion per user          key = user_id
    several characters per user     key = f"{user_id}-{character_id}"

Keys become directory names, so they must match [A-Za-z0-9][A-Za-z0-9_.-]*
(an error, never a silent sanitisation).

Two different layers, on purpose:

    card          derived from what the *user* said; it is prompt material,
                  so the model sees 称呼/忌称 and stops using the wrong name
    canon/gate    built from directive events only; it refuses a reply that
                  violates a rule. A chat line does not become canon by
                  itself -- the user presses 记成规则, or the GM panel calls
                  rule(). So the same sentence changes behaviour twice,
                  through two paths that fail independently.

Error policy.

    E_LOCK        another process holds this key for a moment; retry, keep the
                  user waiting at most a few hundred ms, never drop the turn
    E_CHAIN_*     the store is torn (crash, disk full); the write is refused.
                  Do NOT retry blindly: run `aiinvite verify --dir <store>`
    E_TAMPER      someone edited evidence; same drill, hand it to ops

Environment: AIINVITE_ROOT (default /var/lib/aiinvite/stores), AIINVITE_MODEL.
Run the self-test on the server before trusting the numbers:

    python examples/aiyao_bridge.py --selftest /tmp/aiyao-smoke
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from aiinvite.errors import E_LOCK, AiInviteError
from aiinvite.serve import MemoryService

DEFAULT_ROOT = "/var/lib/aiinvite/stores"
DEFAULT_MODEL = "deepseek-v3"
RETRIES = 3


class AiyaoMemory:
    """The whole integration: warm sessions, per-key locks, retry on E_LOCK."""

    def __init__(self, root=None, model=None, budget=4096, max_sessions=32):
        root = pathlib.Path(root or os.environ.get("AIINVITE_ROOT", DEFAULT_ROOT))
        model = (model or os.environ.get("AIINVITE_MODEL", DEFAULT_MODEL)).strip()
        # max_sessions is the RSS knob: ~46 MB per warm 20k store, ~165 MB per
        # 200k one. On a 2 GB instance stay at 8-16, not 32.
        self.service = MemoryService(root, model, budget=budget, max_sessions=max_sessions)

    # -- chat path -----------------------------------------------------
    def turn(self, key, user_text):
        """Record the user line and return the prompt for your model."""
        return self._call(self.service.turn, key, user_text)

    def reply(self, key, model_text):
        """Gate the model reply before it becomes the companion's words.

        Must be called after the model answers: a refusal is recorded as a
        refusal event *without* the text, and only an allowed reply enters
        evidence. Skipping this call silently disables the actuation gate.
        """
        return self._call(self.service.reply, key, model_text)

    # -- console path --------------------------------------------------
    def view(self, key):
        """card / standing / canon / pins / kid / events for the GM panel."""
        return self._call(self.service.view, key)

    def rule(self, key, text):
        """Append a user-level standing rule (directive/lock), return the view.

        This is the only legal console write. Editing the card file would be
        overwritten by the next derivation; a rule event is auditable and
        survives a rebuild.
        """
        return self._call(self.service.remember, key, text)

    # -- plumbing ------------------------------------------------------
    def _call(self, fn, *args):
        for attempt in range(RETRIES):
            try:
                return fn(*args)
            except AiInviteError as exc:
                if exc.code != E_LOCK or attempt == RETRIES - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))
        raise AssertionError("unreachable")

    def close(self):
        self.service.close()


def _selftest(root, model):
    """Prove the wiring on this machine: card, gate, standing rules, kid."""
    mem = AiyaoMemory(root, model, max_sessions=4)
    try:
        empty = mem.view("u1")
        print("1 empty store      events=%d kid=%s" % (empty["events"], empty["kid"] or "-"))

        turn = mem.turn("u1", "我叫老周，别叫我宝贝")
        print("2 prompt           %d bytes, model=%s" % (len(turn["prompt"].encode("utf-8")), turn["model"]))

        card = mem.view("u1")["card"]
        address = card.get("address") or {}
        print("3 user card        称呼=%s 忌称=%s" % (
            address.get("call") or "-",
            "、".join(item["text"] for item in address.get("never") or []) or "-",
        ))

        # A chat line only reaches the card. The gate reads canon, so it is
        # still open here -- this is the documented "card is not the gate".
        loose = mem.reply("u1", "好的，宝贝")
        print("4 gate before rule allowed=%s rule=%s" % (loose["allowed"], loose["rule"] or "-"))

        ruled = mem.rule("u1", "别叫我宝贝")
        print("5 standing rules   %s" % (ruled["standing"],))

        blocked = mem.reply("u1", "好的，宝贝")
        print("6 gate refuses     allowed=%s rule=%s" % (blocked["allowed"], blocked["rule"]))

        good = mem.reply("u1", "记着呢，老周。")
        print("7 gate allows      allowed=%s rule=%s" % (good["allowed"], good["rule"] or "-"))

        view = mem.view("u1")
        print("8 identity         kid=%s events=%d" % (view["kid"][:12], view["events"]))
    finally:
        mem.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="爱邀 memory bridge self-test")
    parser.add_argument("--selftest", metavar="DIR", help="run against DIR (created if absent)")
    parser.add_argument("--model", default=None, help="model name recorded in the prompt")
    args = parser.parse_args(argv)
    if not args.selftest:
        parser.error("pass --selftest DIR (the same flag CI and the deploy doc use)")
    root = pathlib.Path(args.selftest)
    temporary = not root.exists()
    root.mkdir(parents=True, exist_ok=True)
    try:
        _selftest(root, args.model)
    finally:
        if temporary and not os.environ.get("AIINVITE_KEEP"):
            import shutil

            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
