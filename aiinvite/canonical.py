"""Canonical JSON serialization (RFC 8785 subset) for AI Invite.

Only Python ``dict`` objects may appear at the top level. Lists are allowed
inside an object. Numbers must be integers in the open range (-2**53, 2**53);
floats are rejected because v1 containers never contain them.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .errors import E_NOT_CANONICAL, AiInviteError

INT_LIMIT = 2 ** 53
_SURROGATE_RE = re.compile("[\ud800-\udfff]")
_UNSAFE_RE = re.compile('["\\\\\x00-\x1f\ud800-\udfff]')


def dumps(obj: object) -> bytes:
    """Serialize ``obj`` to canonical UTF-8 bytes, without a trailing newline."""
    if not isinstance(obj, dict):
        raise AiInviteError(E_NOT_CANONICAL, "顶层必须是 JSON 对象")
    return _encode(obj).encode("utf-8")


def _encode(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, int):
        if not -INT_LIMIT < int(value) < INT_LIMIT:
            raise AiInviteError(E_NOT_CANONICAL, "整数超出 v1 允许范围")
        return str(value)
    if isinstance(value, float):
        raise AiInviteError(E_NOT_CANONICAL, "v1 不允许浮点数")
    if isinstance(value, str):
        return _encode_string(value)
    if isinstance(value, dict):
        return _encode_object(value)
    if isinstance(value, list):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    raise AiInviteError(E_NOT_CANONICAL, f"不支持的类型：{type(value).__name__}")


def _encode_object(value: dict[Any, Any]) -> str:
    for key in value:
        if not isinstance(key, str):
            raise AiInviteError(E_NOT_CANONICAL, "对象键必须是字符串")
    parts = [f"{_encode_string(key)}:{_encode(value[key])}" for key in sorted(value)]
    return "{" + ",".join(parts) + "}"


def _encode_string(value: str) -> str:
    if not _UNSAFE_RE.search(value):
        if not unicodedata.is_normalized("NFC", value):
            value = unicodedata.normalize("NFC", value)
        return '"' + value + '"'
    if _SURROGATE_RE.search(value):
        raise AiInviteError(E_NOT_CANONICAL, "字符串包含孤立代理项")
    if not unicodedata.is_normalized("NFC", value):
        value = unicodedata.normalize("NFC", value)
    parts: list[str] = ['"']
    for char in value:
        code = ord(char)
        if char == '"':
            parts.append('\\"')
        elif char == "\\":
            parts.append("\\\\")
        elif code < 0x20:
            parts.append(f"\\u{code:04x}")
        else:
            parts.append(char)
    parts.append('"')
    return "".join(parts)
