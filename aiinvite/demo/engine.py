"""Pure logic behind the demo window: no UI, no hard-coded model calls."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import tempfile
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass

from aiinvite.capsule import append_event, init_store, utc_now, verify_path
from aiinvite.host import HostSession
from aiinvite.persona.pins import derive_pins

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODELS = ("glm4:9b", "qwen3.5:9b")
DEFAULT_MODEL = DEFAULT_MODELS[0]


def make_rewriter(model, timeout=20):
    """Return a rewriter backed by the local model.

    Temperature 0 and a fixed seed are not optional: a rewriter that answers
    differently on the same question would make recall non-reproducible.
    """

    def call(prompt):
        return ollama_caller(
            prompt, model, timeout=timeout, temperature=0.0, seed=42
        )

    return call

class EngineError(RuntimeError):
    """A demo-level failure with a message the window can show."""


def explain_failure(code, body):
    """Turn an Ollama HTTP failure into an instruction the user can follow."""
    text = (body or "").lower()
    if "out of memory" in text or "failed to allocate" in text:
        return (
            "内存不足，模型加载失败：关掉一些占内存的程序（浏览器、微信、编辑器），"
            "或者换一个更小的模型（如 qwen2.5:3b）。"
        )
    if "not found" in text or "no such model" in text:
        return "这个模型还没下载：先在终端运行 ollama pull <模型名>。"
    if code == 500:
        return "模型服务报错了（500）：看一眼 Ollama 的日志，通常是加载失败。"
    return "模型服务返回 " + str(code) + "：" + (body or "")[:120]


def explain_unreachable(url, error):
    """Explain a connection failure: the service, not the model, is missing."""
    return (
        "本地模型服务没有打开（" + url + "）：先启动 Ollama，再试一次。"
        "（原始错误：" + str(error)[:80] + "）"
    )

def ollama_caller(prompt, model, timeout=120, temperature=None, seed=None):
    """Ask a local Ollama model; raise EngineError when it is unreachable."""
    options = {"num_predict": 220}
    if temperature is not None:
        options["temperature"] = temperature
    if seed is not None:
        options["seed"] = seed
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": options,
    }).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore") if hasattr(exc, "read") else ""
        raise EngineError(explain_failure(exc.code, detail)) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise EngineError(explain_unreachable(OLLAMA_URL, exc)) from exc
    except json.JSONDecodeError as exc:
        raise EngineError("模型服务返回了无法解析的内容：" + str(exc)[:80]) from exc
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

    def __init__(self, store, model=None, caller=ollama_caller, now=None, rewriter=None,
                 clue_caller=None):
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
        self._rewriter = rewriter if rewriter is not None else make_rewriter(self.model)
        self._clue_caller = clue_caller

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
            self._session = HostSession(
                self.store,
                self.model,
                now=self._now,
                rewriter=self._rewriter,
                clue_caller=self._clue_caller,
            )
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
        self._learn_in_background()
        return turn

    def _learn_in_background(self):
        """Generate one clue set off the reply path; never block the window."""
        if self._clue_caller is None:
            return

        def run():
            try:
                self._session_object().learn_clues(1)
            except Exception:
                pass

        threading.Thread(target=run, daemon=True).start()

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
