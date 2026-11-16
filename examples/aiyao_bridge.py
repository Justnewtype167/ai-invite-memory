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
    several characters per user     key = key_for(user_id, character_id)

If 爱邀 lets a user switch between characters, use the second form. Switching
a character must switch the key: canon, traits, pins and the kid all belong to
one persona, and mixing two characters in one store would let character A's
rules bind character B.

What that costs, stated plainly: a name the user gives to one character does
not reach the others, because the card is derived from that store's evidence.
Two honest options, in order:

    1. GM fan-out. The console stores the fact once in 爱邀's own user table,
       then calls fan_out_rule() over that user's characters. N appends, each
       one auditable in its own chain; the fact then shows in every character's
       standing rules.
    2. A shared profile layer inside the engine (not implemented). It would
       need a cross-store merge and a decision about what the kid covers.

Start with 1: it is one loop, and it does not touch the evidence model.

Keys become directory names, so they must match [A-Za-z0-9][A-Za-z0-9_.-]*
(an error, never a silent sanitisation). key_for() validates, it does not
rewrite: a user id with ':' or '/' is a bug in the caller, not a name to fix.

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

from aiinvite.errors import E_ARG, E_LOCK, AiInviteError
from aiinvite.serve import MemoryService, check_key

DEFAULT_ROOT = "/var/lib/aiinvite/stores"
DEFAULT_MODEL = "deepseek-v3"
RETRIES = 3


def key_for(user_id, character_id=None):
    """Return the store key for one user, optionally one of their characters.

    The two forms are deliberately different strings: a product that used
    bare user ids and later adds characters must not silently reuse the
    old store as the first character's memory (that would give character B
    the old single-companion history).
    """
    user = str(user_id or "").strip()
    if not user:
        raise AiInviteError(E_ARG, "user_id 不能为空")
    if character_id is None or str(character_id).strip() == "":
        return check_key(user)
    return check_key("%s-%s" % (user, str(character_id).strip()))


def fan_out_rule(mem, user_id, character_ids, text):
    """Write one user-level fact into every character's store.

    This is the 爱邀 answer to 'the user introduced themselves to 小雨 and
    小满 does not know their name': the GM table keeps the fact once, and
    this loop appends it to each character as a directive so every chain
    records where it came from. Returns {character_id: view}; a failing
    character does not stop the others -- collect the errors and retry.
    """
    written, failed = {}, {}
    for character_id in character_ids:
        try:
            written[character_id] = mem.rule(key_for(user_id, character_id), text)
        except AiInviteError as exc:
            failed[character_id] = exc.code
    return {"written": written, "failed": failed}


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

        # Two characters of one user are two memories. Character B must not
        # inherit A's card, and a rule fanned out reaches both.
        first = key_for("u1", "xiaoyu")
        second = key_for("u1", "xiaoman")
        mem.turn(first, "我叫老周")
        print("9 keys             %s / %s" % (first, second))
        print("10 A card          称呼=%s" % ((mem.view(first)["card"].get("address") or {}).get("call") or "-"))
        print("11 B card          称呼=%s events=%d" % (
            (mem.view(second)["card"].get("address") or {}).get("call") or "-",
            mem.view(second)["events"],
        ))
        fan = fan_out_rule(mem, "u1", ["xiaoyu", "xiaoman"], "用户希望被称呼为老周")
        print("12 fan-out          written=%s failed=%s" % (sorted(fan["written"]), fan["failed"] or "-"))
        print("13 B standing      %s" % (mem.view(second)["standing"],))
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
