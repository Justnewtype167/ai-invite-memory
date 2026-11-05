"""Grounded clues: inference at write time, with a gate against invention.

The probe in docs/RESULTS-rewrite.md showed why inference at query time fails:
with no material the model either stays abstract ("memories", "events") or
invents a scene ("hospital", "medicine bottle"). Given the memory text itself,
the same models produce usable clues.

So clues are generated from real text, stored as derived data, and validated:

* an **entity** clue must appear in the source text, or it is dropped;
* a **bridge** clue may be absent from the text (that is the point: "sad" is the
  bridge to "my dog died") but must come from a closed vocabulary.
"""
from __future__ import annotations

import json
import pathlib
import re

DATA = pathlib.Path(__file__).resolve().parent / "data" / "bridges.json"
LABELS = pathlib.Path(__file__).resolve().parent / "data" / "labels.json"
MAX_CLUES = 8
CJK = re.compile(r"[\u4e00-\u9fff]+")


def load_labels(path=None):
    """Return (emotions, categories) from the closed label set."""
    target = path if path is not None else LABELS
    raw = json.loads(target.read_text(encoding="utf-8"))
    emotions = tuple(str(word) for word in raw.get("emotions", []))
    categories = tuple(str(word) for word in raw.get("categories", []))
    return emotions, categories


def build_prompt(text, emotions=None, categories=None):
    """Return a classification instruction: the model picks, it never invents.

    Free generation was measured and replaced: it covered only 4 of 12
    memories, dropped useful phrases, and could invent a scene. Choosing from
    a fixed list covered 12 of 12 in the same probe and cannot fabricate.
    """
    emo = emotions if emotions is not None else load_labels()[0]
    cat = categories if categories is not None else load_labels()[1]
    return (
        "这是用户过去说过的一句话：\n" + (text or "").strip()[:400] + "\n"
        "请判断：\n情绪：从[" + " ".join(emo) + "]里选 1-2 个\n"
        "类别：从[" + " ".join(cat) + "]里选 1 个\n"
        "只输出两行，格式：情绪：X；类别：Y。不要解释。"
    )


def load_bridges(path: pathlib.Path | None = None) -> tuple[str, ...]:
    """Return the closed vocabulary allowed for bridge clues."""
    target = path if path is not None else DATA
    raw = json.loads(target.read_text(encoding="utf-8"))
    return tuple(str(word) for word in raw if str(word).strip())


STOP_CHARS = tuple("我你他的了是在有和也就都")


def _is_entity(piece, source):
    """Return whether one clue word is grounded in the source text."""
    if piece not in source:
        return False
    if len(piece) >= 2:
        return True
    # A single character is allowed only when it is a content word, not glue.
    return piece not in STOP_CHARS


def split_clues(
    text: str, raw: str, bridges: tuple[str, ...] | None = None
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (entities, bridges) that survive the two gates.

    Entities must be substrings of the source text; bridges must be in the
    closed vocabulary. Anything else is invention and is dropped.
    """
    if bridges is None:
        emotions, categories = load_labels()
        bridges = load_bridges() + emotions + categories
    allowed = bridges
    source = text or ""
    entities: list[str] = []
    bridge_hits: list[str] = []
    seen: set[str] = set()
    for chunk in re.split(r"[\s,，、。；;:：\n]+", raw or ""):
        for piece in CJK.findall(chunk):
            if len(piece) < 1 or piece in seen:
                continue
            if piece in allowed:
                seen.add(piece)
                bridge_hits.append(piece)
                continue
            if not _is_entity(piece, source):
                continue
            seen.add(piece)
            entities.append(piece)
    return tuple(entities[:MAX_CLUES]), tuple(bridge_hits[:MAX_CLUES])


def generate_clues(text: str, caller, bridges=None):
    """Ask the caller for clues about one memory and return the gated pairs."""
    if caller is None:
        return (), ()
    try:
        raw = caller(build_prompt(text))
    except Exception:
        return (), ()
    return split_clues(text, str(raw or ""), bridges)
