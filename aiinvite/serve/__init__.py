"""Server-side composition: many users, one process (M37).

``aiinvite.host`` owns one conversation over one store. A backend that serves
many users needs three more things and nothing else:

* one warm session per store key, so a turn does not pay the cold start;
* one lock per key, so two turns for the same user never interleave appends;
* a JSON view a management console can read without touching internals.

Not in this layer: HTTP, authentication, model calls, and edits to derived
data. The user card is derived from evidence: a console that writes the card
file directly loses the edit at the next derivation. ``remember`` appends a
directive(kind=lock) event instead, the same path the chat itself uses, so the
edit is auditable, recomputable and survives a rebuild.

One key is one memory. A product where each user has one companion uses
``key = user_id``. A product with several characters per user needs one key
per character (``f"{user_id}-{character_id}"``), because the kernel is one
persona over one evidence chain. Keys must be filesystem-safe.

A backend must not run two processes over one store directory: appends are
serialised per process only. Shard by key across processes, or keep one.
"""
from __future__ import annotations

import pathlib
import re
import threading
from collections import OrderedDict

from aiinvite.capsule import append_event, utc_now
from aiinvite.errors import E_ARG, E_IO, AiInviteError
from aiinvite.host import HostSession
from aiinvite.kernel.errors import KernelError
from aiinvite.pcs.probes import load_rules_v2
from aiinvite.persona.pins import derive_pins

KEY_LIMIT = 128
WINDOWS_RESERVED = frozenset(
    ["con", "prn", "aux", "nul"]
    + [f"com{index}" for index in range(1, 10)]
    + [f"lpt{index}" for index in range(1, 10)]
)
KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,%d}$" % (KEY_LIMIT - 1))


def check_key(key: str) -> str:
    """Return a key a store directory can be named after, or raise E_ARG.

    Keys come from the caller (a user id, a user id plus a character id).
    They are used as directory names, so the check is a security boundary:
    no separators, no parent references, no Windows device names.
    """
    text = (key or "").strip()
    if not text:
        raise AiInviteError(E_ARG, "key 不能为空")
    if not KEY_PATTERN.match(text):
        raise AiInviteError(
            E_ARG,
            f"key 只能包含 ASCII 字母、数字、下划线、点和短横，且以字母或数字开头：{text!r}",
        )
    stem = text.split(".", 1)[0].lower()
    if stem in WINDOWS_RESERVED or text.endswith("."):
        raise AiInviteError(E_ARG, f"key 在 Windows 上不是合法目录名：{text!r}")
    return text


class MemoryService:
    """One process, many stores: warm sessions, per-key locks, JSON views.

    A turn is ``turn(key, text)`` for the user line; the host runs its model
    on the returned prompt and calls ``remember``/``pin``/``view`` from the
    console. The service never calls a model: the backend owns that.
    """

    def __init__(self, root, model, budget=4096, max_sessions=32, now=None):
        """Open (or create) the user root; nothing else is read eagerly."""
        self.root = pathlib.Path(root)
        self.model = (model or "").strip()
        if not self.model:
            raise AiInviteError(E_ARG, "model 不能为空")
        if not isinstance(budget, int) or budget < 256:
            raise AiInviteError(E_ARG, "budget 必须是 >= 256 的整数")
        if not isinstance(max_sessions, int) or max_sessions < 1:
            raise AiInviteError(E_ARG, "max_sessions 必须是 >= 1 的整数")
        if self.root.exists() and not self.root.is_dir():
            raise AiInviteError(E_IO, f"路径不是目录：{self.root}")
        self.root.mkdir(parents=True, exist_ok=True)
        self.budget = budget
        self.max_sessions = max_sessions
        self.now = now
        self._sessions: OrderedDict[str, HostSession] = OrderedDict()
        # Locks are never evicted: a thread may be waiting on one while its
        # session is replaced, and two locks for one key would break the only
        # guarantee this layer gives. They cost a few bytes per key seen.
        self._locks: dict[str, threading.RLock] = {}
        self._registry = threading.Lock()

    # -- internals -----------------------------------------------------
    def store_for(self, key: str) -> pathlib.Path:
        """Return the store directory for a key, creating nothing."""
        return self.root / check_key(key)

    def _lock(self, key: str) -> threading.RLock:
        text = check_key(key)
        with self._registry:
            lock = self._locks.get(text)
            if lock is None:
                lock = self._locks[text] = threading.RLock()
            return lock

    def _session(self, key: str) -> HostSession:
        """Return the warm session for a key; the caller holds the key lock."""
        with self._registry:
            session = self._sessions.get(key)
            if session is not None:
                self._sessions.move_to_end(key)
                return session
        # Cold start happens outside the registry lock: on a 200k store it is
        # tens of seconds, and no other user should wait behind it.
        session = HostSession(
            self.store_for(key), self.model, budget=self.budget, now=self.now
        )
        with self._registry:
            existing = self._sessions.get(key)
            if existing is not None:
                self._sessions.move_to_end(key)
                return existing
            self._sessions[key] = session
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)
            return session

    def _events(self, session: HostSession):
        """Read evidence once per call; a broken store must not kill a view."""
        try:
            return session._events()
        except Exception:  # noqa: BLE001 - empty store and torn chains degrade
            return []

    # -- writes --------------------------------------------------------
    def turn(self, key: str, text: str, t: str | None = None) -> dict:
        """Record the user line and return the prompt for the model."""
        body = (text or "").strip()
        if not body:
            raise AiInviteError(E_ARG, "text 不能为空")
        with self._lock(key):
            session = self._session(check_key(key))
            event = session.on_user(body, t or utc_now())
            prompt = session.prompt_for(body)
            return {
                "key": key,
                "prompt": prompt,
                "recalled": list(session.last_recalled),
                "event_id": getattr(event, "id", "") or "",
                "model": self.model,
            }

    def remember(self, key: str, text: str, t: str | None = None) -> dict:
        """Make the line a standing rule (directive/lock), then return the view.

        This is the console's write path. It is evidence, not configuration:
        the rule enters the kernel canon, moves the kid, and survives a
        rebuild. The card stays derived -- never write it from a console.
        """
        body = (text or "").strip()
        if not body:
            raise AiInviteError(E_ARG, "text 不能为空")
        with self._lock(key):
            session = self._session(check_key(key))
            append_event(
                session.store,
                text=body,
                t=t or utc_now(),
                type="directive",
                kind="lock",
            )
            session._view_cache = None
            return self.view(key)

    def pin(self, key: str, event_id: str, t: str | None = None) -> dict:
        """Force one memory into every later prompt; returns the view."""
        with self._lock(key):
            session = self._session(check_key(key))
            session._write_pin((event_id or "").strip(), "pin")
            return self.view(key)

    def unpin(self, key: str, event_id: str, t: str | None = None) -> dict:
        """Stop forcing one memory; returns the view."""
        with self._lock(key):
            session = self._session(check_key(key))
            session._write_pin((event_id or "").strip(), "unpin")
            return self.view(key)

    def reply(self, key: str, text: str, t: str | None = None) -> dict:
        """Gate the model reply before it enters evidence; return the verdict.

        A refused reply is recorded as a refusal event without its text, which
        is the difference between "the model said it" and "the companion said
        it". A backend that skips this call loses the actuation gate.
        """
        body = (text or "").strip()
        if not body:
            raise AiInviteError(E_ARG, "text 不能为空")
        with self._lock(key):
            session = self._session(check_key(key))
            verdict = session.reply(body, t or utc_now())
            return {
                "allowed": bool(verdict.allowed),
                "rule": verdict.rule or "",
                "detail": verdict.detail,
                "segment": verdict.segment_index,
            }
    # -- reads ---------------------------------------------------------
    def view(self, key: str) -> dict:
        """Return the console view: identity, card, rules, pins, counters."""
        with self._lock(check_key(key)):
            session = self._session(check_key(key))
            events = self._events(session)
            kid = ""
            head = ""
            try:
                kernel = session._kernel(events)
                kid = kernel.kid
                head = kernel.head
            except (KernelError, AiInviteError):
                kernel = None
            card: dict = {}
            self_md = ""
            try:
                _, _, persona_view = session._card_and_persona(events)
            except (KernelError, AiInviteError):
                persona_view = None
            if persona_view is not None and persona_view.user_card is not None:
                card = persona_view.user_card.to_payload()
                self_md = persona_view.self_md
            pins = [
                {"event_id": pin.event_id, "text": pin.text}
                for pin in derive_pins(events)
            ]
            return {
                "key": key,
                "kid": kid,
                "head": head,
                "model": self.model,
                "events": len(events),
                "card": card,
                "canon": [entry.text for entry in kernel.canon] if kernel else [],
                "persona": self_md,
                "pins": pins,
                "rules": [rule.text for rule in load_rules_v2()],
                "store": str(session.store),
            }

    def stats(self) -> dict:
        """Return the session-pool counters; no store is touched."""
        with self._registry:
            return {"sessions": len(self._sessions), "keys": len(self._locks)}

    def close(self) -> None:
        """Drop every warm session. Data stays on disk; the next turn rebuilds."""
        with self._registry:
            self._sessions.clear()


__all__ = ["MemoryService", "check_key"]