"""Pure logic behind the demo window: no UI, no hard-coded model calls."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass

from aiinvite.capsule import append_event, init_store, utc_now, verify_path
from aiinvite.host import HostSession
from aiinvite.persona.pins import derive_pins

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODELS = ("glm4:9b", "qwen3.5:9b")
DEFAULT_MODEL = DEFAULT_MODELS[0]


class EngineError(RuntimeError):
    """A demo-level failure with a message the window can show."""


def ollama_caller(prompt: str, model: str, timeout: int = 120) -> str:
    """Ask a local Ollama model; raise EngineError when it is unreachable."""
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"num_predict": 220},
    }).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError) as exc:
        raise EngineError(f"cannot reach Ollama at {OLLAMA_URL}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EngineError(f"Ollama returned non-JSON: {exc}") from exc
    text = str(body.get("response", "")).strip()
    if not text:
        raise EngineError(f"{model} returned an empty reply")
    return text


@dataclass(frozen=True)
class Turn:
    """One exchange, as the window shows it."""

    role: str
    text: str
    refused: bool = False


class DemoEngine:
    """A conversation plus the four things the demo must make visible."""

    def __init__(self, store, model=None, caller=ollama_caller, now=None):
        self.store = pathlib.Path(store)
        self.model = model or DEFAULT_MODELS[0]
        self._caller = caller
        self._now = now
        if not (self.store / "chain.json").is_file():
            # A second launch must reuse the memory, not crash on it.
            init_store(self.store)
        self._session = None
        self.turns = []
        self.last_user_event = ""

    def remember(self, text):
        """Write the line as a standing rule (directive/lock), not a chat turn.

        This is the difference the demo exists to show: a turn is remembered,
        a directive becomes canon and the actuation gate enforces it.
        """
        text = (text or "").strip()
        if not text:
            raise EngineError("empty rule")
        append_event(self.store, text=text, t=utc_now(), type="directive", kind="lock")
        self._session = None
        return self.snapshot()

    def pin_last(self):
        """Pin the newest user turn so it reaches every later prompt."""
        if not self.last_user_event:
            raise EngineError("还没有可钉住的一轮")
        self._session_object().pin(self.last_user_event)
        return self.snapshot()

    def switch_model(self, model):
        """Change the model only; evidence and identity stay untouched.

        The kid is repeated here so the window can show it before and after
        without sending a turn: every sent turn is evidence and moves the kid.
        """
        before = self.current_kid()
        self.model = model
        return {"kid_before": before, "kid_after": self.current_kid()}

    def _session_object(self):
        if self._session is None:
            self._session = HostSession(self.store, self.model, now=self._now)
        self._session.model = self.model
        return self._session

    def send(self, text):
        """Record the user turn, ask the model, gate the reply, record it."""
        text = (text or "").strip()
        if not text:
            raise EngineError("empty input")
        session = self._session_object()
        event = session.on_user(text, utc_now())
        self.last_user_event = event.id
        self.turns.append(Turn(role="user", text=text))
        prompt = session.prompt_for(text)
        raw = self._caller(prompt, self.model)
        verdict = session.reply(raw, utc_now())
        turn = Turn(role="assistant", text=raw, refused=not verdict.allowed)
        self.turns.append(turn)
        return turn

    def current_kid(self):
        """Return the kid of the evidence as it stands now (no write)."""
        try:
            return self._session_object()._kernel().kid
        except Exception:
            return ""

    def snapshot(self):
        """Return the numbers and cards the window renders."""
        session = self._session_object()
        try:
            events_for_pins = session._events()
        except Exception:  # noqa: BLE001
            events_for_pins = []
        kid = ""
        card = ""
        traits = []
        canon = []
        events = 0
        try:
            kernel = session._kernel()
            kid = kernel.kid
            canon = [entry.text for entry in kernel.canon]
            view = session._card_and_persona()[2]
        except Exception:
            view = None
        try:
            events = verify_path(self.store).events
        except Exception:
            events = 0
        if view is not None:
            card = view.user_card.text().strip() if view.user_card else ""
            traits = [item.name for item in view.traits]
        return {
            "kid": kid,
            "events": events,
            "card": card,
            "traits": traits,
            "canon": canon,
            "pinned": [pin.text for pin in derive_pins(events_for_pins)],
            "model": self.model,
            "store": str(self.store),
        }

    def export_to(self, target):
        """Copy the store to a folder the user can carry."""
        target = pathlib.Path(target)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(self.store, target)
        verify_path(target)
        return target

    def import_from(self, source):
        """Replace this store with a copied one; identity must already match."""
        source = pathlib.Path(source)
        verify_path(source)
        if self.store.exists():
            shutil.rmtree(self.store)
        shutil.copytree(source, self.store)
        self._session = None
        return self.store

    def verify(self):
        """Return the verified event count; raises on tampering."""
        return verify_path(self.store).events


def scratch_store():
    """Return a throwaway store path (tests and experiments only)."""
    return pathlib.Path(tempfile.mkdtemp(prefix="aiinvite_demo_")) / "memory"


def default_store():
    """Return the persistent store the window opens by default.

    A demo that forgets you every launch is not a demo of memory.
    """
    if os.name == "nt":
        base = pathlib.Path(os.environ.get("APPDATA") or pathlib.Path.home())
    else:
        base = pathlib.Path(os.environ.get("XDG_DATA_HOME") or pathlib.Path.home() / ".local" / "share")
    return base / "AIInvite" / "memory"
