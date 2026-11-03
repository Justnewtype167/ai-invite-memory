"""Legacy capsule data model, shared constants and identity recomputation (M15)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from aiinvite.canonical import dumps
from aiinvite.kernel.compiler import compile_kernel
from aiinvite.kernel.errors import KernelError
from aiinvite.kernel.kernel import Policy

from aiinvite.succession.errors import E_SUCC_SCHEMA, SuccessionError

LEGACY_FORMAT = "aiinvite.legacy/1"
FORMAT_VERSION = 1
MODE_INHERIT = "inherit"
REASONS = ("third_party", "private", "requested")

MANIFEST_PATH = "manifest.json"
CHAIN_PATH = "chain.json"
REVIVAL_PATH = "REVIVAL.md"
POLICY_PATH = "policy.json"
REDACTION_PATH = "redaction.json"
SUCCESSION_PATH = "succession.json"
LETTERS_DIR = "letters"
BLOBS_DIR = "blobs"
EVIDENCE_DIR = "evidence"

MANIFEST_KEYS = frozenset({
    "format", "format_version", "created", "kid", "policy_digest",
    "head", "files", "signature",
})
REDACTION_KEYS = frozenset({
    "excluded", "reason", "redacted_kid", "origin_kid", "evidence_sha256",
})
SUCCESSION_KEYS = frozenset({
    "successor_kid", "derived_from", "redacted", "created", "mode",
})
POLICY_KEYS = frozenset({
    "allow_fallback", "delta_limit", "force_fallback", "now",
    "require_proposals",
})

HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
LETTER_RE = re.compile(r"^letters/letter-[0-9]{1,3}\.txt$")
EVIDENCE_RE = re.compile(r"^evidence/(seg-[0-9]{4})\.jsonl$")
BLOB_RE = re.compile(r"^blobs/([0-9a-f]{64})$")


@dataclass(frozen=True)
class Letter:
    """One plain-text note left for whoever takes the capsule."""

    who: str
    when: str
    to: str
    text: str

    def to_text(self) -> str:
        """Render this letter as the canonical UTF-8 file body."""
        return f"who: {self.who}\nwhen: {self.when}\nto: {self.to}\n\n{self.text}\n"

    @classmethod
    def from_text(cls, body: str) -> "Letter":
        """Parse one letter file, raising ``E_SUCC_SCHEMA`` when malformed."""
        lines = body.split("\n")
        if len(lines) < 5 or lines[3] != "":
            raise SuccessionError(E_SUCC_SCHEMA, "letter 缺少分隔空行")
        for index, name in enumerate(("who", "when", "to")):
            prefix = f"{name}: "
            value = lines[index][len(prefix):] if lines[index].startswith(prefix) else ""
            if not value.strip():
                raise SuccessionError(E_SUCC_SCHEMA, f"letter 缺少 {name}")
        text = "\n".join(lines[4:]).strip()
        if not text:
            raise SuccessionError(E_SUCC_SCHEMA, "letter 缺少正文")
        return cls(
            lines[0][len("who: "):],
            lines[1][len("when: "):],
            lines[2][len("to: "):],
            text,
        )


@dataclass(frozen=True)
class LegacyInfo:
    """What a legacy capsule declares, after verification."""

    kid: str
    origin_kid: str
    successor_kid: str
    events: int
    segments: int
    redacted: bool
    excluded: tuple[str, ...]


def policy_bytes(policy: Policy) -> bytes:
    """Serialize a policy as canonical bytes for shipping inside the capsule."""
    return dumps({
        "allow_fallback": policy.allow_fallback,
        "delta_limit": policy.delta_limit,
        "force_fallback": policy.force_fallback,
        "now": policy.now,
        "require_proposals": policy.require_proposals,
    })


def load_policy(path: Path) -> Policy:
    """Read a shipped ``policy.json`` and rebuild the exact ``Policy``."""
    try:
        data = path.read_bytes()
    except OSError as error:
        raise SuccessionError(E_SUCC_SCHEMA, f"读取失败：{path}") from error
    return policy_from_bytes(data)


def policy_from_bytes(data: bytes) -> Policy:
    """Decode policy bytes and validate every field."""
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SuccessionError(E_SUCC_SCHEMA, "policy.json 解码失败") from error
    if not isinstance(payload, dict):
        raise SuccessionError(E_SUCC_SCHEMA, "policy.json 必须是对象")
    if set(payload) != POLICY_KEYS:
        raise SuccessionError(E_SUCC_SCHEMA, "policy.json 字段缺失或多余")
    delta = payload["delta_limit"]
    if isinstance(delta, bool) or not isinstance(delta, int) or not 0 <= delta <= 1000:
        raise SuccessionError(E_SUCC_SCHEMA, "delta_limit 必须是 0-1000 的整数")
    for name in ("allow_fallback", "force_fallback", "require_proposals"):
        if not isinstance(payload[name], bool):
            raise SuccessionError(E_SUCC_SCHEMA, f"{name} 必须是布尔值")
    now = payload["now"]
    if now is not None and not isinstance(now, str):
        raise SuccessionError(E_SUCC_SCHEMA, "now 必须是字符串或 null")
    return Policy(
        now=now,
        delta_limit=delta,
        require_proposals=bool(payload["require_proposals"]),
        allow_fallback=bool(payload["allow_fallback"]),
        force_fallback=bool(payload["force_fallback"]),
    )


def recompute_kid(store: Path, policy: Policy) -> str:
    """Recompile a store under ``policy`` and return its content identity."""
    try:
        return compile_kernel(store, policy, verify=False).kid
    except KernelError as error:
        raise SuccessionError(
            E_SUCC_SCHEMA, f"无法重算 kid：{error}"
        ) from error


def digest(data: bytes) -> str:
    """Return the lowercase sha256 hex digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def canonical_files(entries: Mapping[str, bytes]) -> list[dict[str, object]]:
    """Return the sorted ``manifest.files`` view of a set of capsule entries."""
    return [
        {"path": name, "sha256": digest(data), "bytes": len(data)}
        for name, data in sorted(entries.items())
    ]
