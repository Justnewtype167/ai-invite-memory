"""Derived clue storage: one JSON file beside the index, never in the kid.

Clues are expensive (about 12 s per memory on a 9B local model), so they are
generated lazily and cached. The cache is derived data: deleting it must change
nothing but the cost of the next recall. Every entry carries the sha256 of the
text it was built from, so an edited memory cannot inherit a stale clue.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

from aiinvite.recall.clues import generate_clues

CLUE_DIR = ".clues"
CLUE_FILE = "clues.json"


def _sha(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class ClueStore:
    """Load, generate and cache recall clues for one store."""

    def __init__(self, store, caller=None):
        self.store = pathlib.Path(store)
        self.caller = caller
        self._entries = self._load()

    @property
    def path(self):
        return self.store / CLUE_DIR / CLUE_FILE

    def _load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _save(self):
        target = self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self._entries, ensure_ascii=False, sort_keys=True, indent=1),
            encoding="utf-8",
        )

    def clue_text(self, event_id):
        """Return the stored clue text for one event, or an empty string."""
        entry = self._entries.get(event_id)
        if not isinstance(entry, dict):
            return ""
        parts = list(entry.get("entities", [])) + list(entry.get("bridges", []))
        return " ".join(str(part) for part in parts)

    def pairs(self):
        """Return (event_id, entities, bridges) for every cached memory.

        Entities and bridges stay separate: retrieval treats a grounded entity
        differently from a vocabulary bridge, because only one of them is
        verifiable against the source text.
        """
        result = []
        for key, entry in self._entries.items():
            if not isinstance(entry, dict):
                continue
            entities = " ".join(str(part) for part in entry.get("entities", []))
            bridges = " ".join(str(part) for part in entry.get("bridges", []))
            if entities or bridges:
                result.append((key, entities, bridges))
        return result

    def ensure(self, event_id, text):
        """Generate clues for one memory when missing or stale."""
        if self.caller is None or not event_id or not text:
            return False
        entry = self._entries.get(event_id)
        if isinstance(entry, dict) and entry.get("sha") == _sha(text):
            return False
        entities, bridges = generate_clues(text, self.caller)
        if not entities and not bridges:
            return False
        self._entries[event_id] = {
            "sha": _sha(text),
            "entities": list(entities),
            "bridges": list(bridges),
        }
        self._save()
        return True

    def learn(self, events, limit=1):
        """Generate at most limit missing clue sets, newest events first."""
        built = 0
        for event in sorted(events, key=lambda item: item.event_id, reverse=True):
            if built >= limit:
                break
            if self.ensure(event.event_id, event.text):
                built += 1
        return built

    def clear(self):
        """Drop the cache; the next recall rebuilds what it needs."""
        self._entries = {}
        try:
            self.path.unlink()
        except OSError:
            pass


def clue_pairs(store):
    """Return cached clue pairs without generating anything."""
    return ClueStore(store).pairs()
