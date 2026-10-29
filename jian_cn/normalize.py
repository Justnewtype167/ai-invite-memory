"""Text normalization: NFC, zero-width, width, traditional to simplified, spaces."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from jian_cn.errors import CnError, E_CN_DATA

_DATA_DIR = Path(__file__).resolve().parent / "data"

# Zero-width and bidi control characters that must never reach the output.
_ZERO_WIDTH = dict.fromkeys(
    [0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2060, 0xFEFF]
)

_FULLWIDTH = {code: code - 0xFEE0 for code in range(0xFF01, 0xFF5F)}
_FULLWIDTH[0x3000] = 0x20

_WS = re.compile(r"[ \t\r\n\f\v]+")


def _load_pairs() -> dict[str, str]:
    path = _DATA_DIR / "variants.json"
    try:
        raw = path.read_bytes().decode("utf-8")
        payload = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise CnError(E_CN_DATA, f"无法读取 variants.json：{exc}") from exc
    pairs = payload.get("pairs") if isinstance(payload, dict) else None
    if not isinstance(pairs, list):
        raise CnError(E_CN_DATA, "variants.json 缺少 pairs 数组")
    mapping: dict[str, str] = {}
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2:
            raise CnError(E_CN_DATA, "variants.json 的 pair 不是二元数组")
        trad, simp = pair
        if not isinstance(trad, str) or not isinstance(simp, str):
            raise CnError(E_CN_DATA, "variants.json 的 pair 含非字符串")
        if len(trad) != 1 or len(simp) != 1:
            raise CnError(E_CN_DATA, "variants.json 只允许字符级映射")
        mapping[trad] = simp
    return mapping


_TRAD_TO_SIMP = _load_pairs()


def _char_to_simplified(ch: str) -> str:
    """Map one character to its simplified form; unknown characters stay as-is."""
    return _TRAD_TO_SIMP.get(ch, ch)


def normalize(text: str) -> str:
    """Return the canonical form used by every M2 module.

    Order is fixed: NFC, strip zero-width, full-width to half-width (ASCII only),
    traditional to simplified (character level only), collapse whitespace.
    """
    if not isinstance(text, str):
        raise TypeError("normalize() expects str")
    out = unicodedata.normalize("NFC", text)
    out = out.translate(_ZERO_WIDTH)
    out = out.translate(_FULLWIDTH)
    out = "".join(_char_to_simplified(ch) for ch in out)
    out = _WS.sub(" ", out).strip()
    return out
