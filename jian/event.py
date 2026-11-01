"""Event model, field validation and event hashing.

``turn`` keeps its M1 shape exactly. Six further types share the same
canonical body and hash rule, so old capsules keep verifying byte for byte.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .canonical import dumps
from .errors import E_SCHEMA, JianError

SEGMENT_MAX_EVENTS = 100
TEXT_MAX_CHARS = 8000
PROPOSAL_TEXT_MAX_CHARS = 500
REFUSAL_TEXT_MAX_CHARS = 40
SUMMARY_MAX_CHARS = 200
MODEL_MAX_CHARS = 64
PROMPT_SHA_MAX_CHARS = 64
QUANT_MAX_CHARS = 32
WEIGHTS_SHA_MAX_CHARS = 64
TEMP_MILLI_MIN = 0
TEMP_MILLI_MAX = 2000
SEED_MIN = 0
SEED_MAX = 2 ** 31 - 1
GENESIS_PREV = "0" * 64

ID_RE = re.compile(r"^ev_[0-9]{6}$")
SEG_RE = re.compile(r"^seg-[0-9]{4}$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
PROMPT_SHA_RE = re.compile(r"^[0-9a-fA-F]{1,64}$")
WEIGHTS_SHA_RE = re.compile(r"^[0-9a-fA-F]{1,64}$")
TIME_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
PAYLOAD_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
TRACE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

ROLES = ("user", "assistant")
MODALITIES = ("text", "audio", "vision", "action", "sensor")
REFUSAL_TARGETS = ("text", "action", "both")
EVENT_TYPES = (
    "turn", "feedback", "directive", "milestone", "checkpoint", "proposal", "refusal",
)
FIELDS = (
    "v", "id", "ep", "t", "type", "role", "text", "prev", "hash", "kind",
    "target", "model", "prompt_sha", "quant", "weights_sha", "temp_milli", "seed",
    "trace",
)

COMMON_FIELDS = frozenset({"v", "id", "ep", "t", "type", "text", "prev", "hash"})
COMMON_FIELDS_V2 = frozenset({
    "v", "id", "ep", "t", "type", "modality", "payload", "summary", "prev", "hash",
})
_TYPE_FIELDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "turn": (("role",), ()),
    "feedback": (("kind",), ("target",)),
    "directive": (("kind",), ()),
    "milestone": ((), ()),
    "checkpoint": ((), ()),
    "proposal": (
        ("target", "model", "prompt_sha"),
        ("quant", "weights_sha", "temp_milli", "seed"),
    ),
    "refusal": (("kind", "target", "trace"), ()),
}
KIND_VALUES: dict[str, tuple[str, ...]] = {
    "feedback": ("praise", "correction"),
    "directive": ("lock", "unlock", "rule"),
    "refusal": ("gate",),
}


@dataclass(frozen=True)
class Event:
    """One immutable evidence event."""

    v: int
    id: str
    ep: str
    t: str
    type: str
    role: str | None
    text: str
    prev: str
    hash: str
    kind: str | None = None
    target: str | None = None
    model: str | None = None
    prompt_sha: str | None = None
    quant: str | None = None
    weights_sha: str | None = None
    temp_milli: int | None = None
    seed: int | None = None
    modality: str | None = None
    payload: str | None = None
    summary: str | None = None
    trace: str | None = None

    def body(self) -> dict[str, object]:
        """Return the hashed view of this event; the ``hash`` field is excluded."""
        body: dict[str, object] = {
            "v": self.v,
            "id": self.id,
            "ep": self.ep,
            "t": self.t,
            "type": self.type,
            "prev": self.prev,
        }
        if self.v == 2:
            body["modality"] = self.modality
            body["payload"] = self.payload
            body["summary"] = self.summary
        else:
            body["text"] = self.text
        if self.role is not None:
            body["role"] = self.role
        if self.kind is not None:
            body["kind"] = self.kind
        if self.target is not None:
            body["target"] = self.target
        if self.model is not None:
            body["model"] = self.model
        if self.prompt_sha is not None:
            body["prompt_sha"] = self.prompt_sha
        if self.quant is not None:
            body["quant"] = self.quant
        if self.weights_sha is not None:
            body["weights_sha"] = self.weights_sha
        if self.temp_milli is not None:
            body["temp_milli"] = self.temp_milli
        if self.seed is not None:
            body["seed"] = self.seed
        if self.trace is not None:
            body["trace"] = self.trace
        return body

    def as_dict(self) -> dict[str, object]:
        """Return the full serialized view of this event, including ``hash``."""
        data = self.body()
        data["hash"] = self.hash
        return data

    def to_line(self) -> bytes:
        """Serialize this event as one canonical JSONL line ending with a newline."""
        return dumps(self.as_dict()) + b"\n"


def utc_now() -> str:
    """Return the current UTC time in the canonical ``...Z`` form."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def body_bytes(event: Event) -> bytes:
    """Serialize the hashed body of an event with canonical rules."""
    return dumps(event.body())


def event_digest(event: Event) -> str:
    """Return the chain hash of an event using the canonical body."""
    payload = event.prev.encode("ascii") + b"\n" + body_bytes(event)
    return hashlib.sha256(payload).hexdigest()


def event_text(data: dict[str, object]) -> str:
    """Return the retrieval text of a decoded event.

    v1 events carry ``text``; v2 events carry ``summary`` only. The accessor
    is the single entry point so upper layers never read a modality-specific
    field directly. Events with neither field yield the empty string.
    """
    if data.get("v") == 2:
        value = data.get("summary")
    else:
        value = data.get("text")
    return value if isinstance(value, str) else ""


def normalize_time(value: str) -> str:
    """Convert a timezone-aware ISO 8601 string to ``YYYY-MM-DDTHH:MM:SSZ``."""
    if not isinstance(value, str):
        raise JianError(E_SCHEMA, "t 必须是字符串")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise JianError(E_SCHEMA, f"t 不是合法的 ISO 8601：{value}") from exc
    if parsed.tzinfo is None:
        raise JianError(E_SCHEMA, "t 必须带时区")
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_id(seq: int) -> str:
    """Return the canonical event id for a 1-based global sequence number."""
    if seq < 1 or seq > 999999:
        raise JianError(E_SCHEMA, "事件序号超出 6 位十进制范围")
    return f"ev_{seq:06d}"


def compute_hash(prev: str, body: dict[str, object]) -> str:
    """Hash one event body using the previous hash as chain input."""
    if not HEX_RE.match(prev):
        raise JianError(E_SCHEMA, "prev 必须是 64 位小写十六进制")
    payload = prev.encode("ascii") + b"\n" + dumps(body)
    return hashlib.sha256(payload).hexdigest()


def new_event(
    seq: int,
    ep: str,
    stamp: str,
    role: str | None,
    text: str | None,
    prev: str,
    *,
    type: str = "turn",
    kind: str | None = None,
    target: str | None = None,
    model: str | None = None,
    prompt_sha: str | None = None,
    quant: str | None = None,
    weights_sha: str | None = None,
    temp_milli: int | None = None,
    seed: int | None = None,
    modality: str | None = None,
    payload: str | None = None,
    summary: str | None = None,
    trace: str | None = None,
) -> Event:
    """Build and hash a new event after validating every field.

    Without ``modality``/``payload``/``summary`` the M1 envelope (v1) is
    written with ``text``. With all three the v2 envelope is written and
    ``text`` must be None, because v2 forbids it. ``trace`` is required by
    ``refusal`` and forbidden everywhere else.
    """
    if modality is None and payload is None and summary is None:
        version = 1
        (event_type, role, kind, target, model, prompt_sha, quant, weights_sha,
         temp_milli, seed, trace) = _validate_fields(
            type, role, text, kind, target, model, prompt_sha,
            quant, weights_sha, temp_milli, seed, trace,
        )
    else:
        if text is not None:
            raise JianError(E_SCHEMA, "v2 事件禁止 text 字段")
        version = 2
        (event_type, role, kind, target, model, prompt_sha, quant, weights_sha,
         temp_milli, seed, trace) = _validate_typed_fields(
            type, role, kind, target, model, prompt_sha,
            quant, weights_sha, temp_milli, seed, trace,
        )
        _check_v2_content(modality, payload, summary)
    if not SEG_RE.match(ep):
        raise JianError(E_SCHEMA, f"非法段名：{ep}")
    if not HEX_RE.match(prev):
        raise JianError(E_SCHEMA, "prev 必须是 64 位小写十六进制")
    normalized = normalize_time(stamp)
    event_id = format_id(seq)
    body: dict[str, object] = {
        "v": version,
        "id": event_id,
        "ep": ep,
        "t": normalized,
        "type": event_type,
        "prev": prev,
    }
    if version == 2:
        body["modality"] = modality
        body["payload"] = payload
        body["summary"] = summary
    else:
        body["text"] = text
    if role is not None:
        body["role"] = role
    if kind is not None:
        body["kind"] = kind
    if target is not None:
        body["target"] = target
    if model is not None:
        body["model"] = model
    if prompt_sha is not None:
        body["prompt_sha"] = prompt_sha
    if quant is not None:
        body["quant"] = quant
    if weights_sha is not None:
        body["weights_sha"] = weights_sha
    if temp_milli is not None:
        body["temp_milli"] = temp_milli
    if seed is not None:
        body["seed"] = seed
    if trace is not None:
        body["trace"] = trace
    digest = compute_hash(prev, body)
    return Event(
        version, event_id, ep, normalized, event_type, role, text if version == 1 else "",
        prev, digest, kind, target, model, prompt_sha, quant, weights_sha,
        temp_milli, seed,
        modality if version == 2 else None,
        payload if version == 2 else None,
        summary if version == 2 else None,
        trace,
    )


def parse_event(data: object) -> Event:
    """Validate a decoded JSON object and return an :class:`Event`."""
    if not isinstance(data, dict):
        raise JianError(E_SCHEMA, "事件必须是 JSON 对象")
    event_type = data.get("type")
    if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
        raise JianError(E_SCHEMA, f"未知事件类型：{event_type}")
    required, optional = _TYPE_FIELDS[event_type]
    version = data.get("v")
    if isinstance(version, bool) or not isinstance(version, int) or version not in (1, 2):
        raise JianError(E_SCHEMA, "v 必须为整数 1 或 2")
    if version == 2 and "text" in data:
        raise JianError(E_SCHEMA, "v2 事件禁止 text 字段")
    common = COMMON_FIELDS_V2 if version == 2 else COMMON_FIELDS
    allowed = common | set(required) | set(optional)
    if not set(data) <= allowed or not common <= set(data):
        raise JianError(E_SCHEMA, f"{event_type} 事件字段缺失或多余")
    missing = [name for name in required if name not in data]
    if missing:
        raise JianError(E_SCHEMA, f"{event_type} 事件缺少字段 {missing[0]}")
    event_id = _string_field(data, "id")
    if not ID_RE.match(event_id):
        raise JianError(E_SCHEMA, f"非法事件 id：{event_id}", event_id)
    segment = _string_field(data, "ep")
    if not SEG_RE.match(segment):
        raise JianError(E_SCHEMA, f"事件 {event_id} 的段名非法", event_id)
    stamp = _string_field(data, "t")
    if not TIME_RE.match(stamp):
        raise JianError(E_SCHEMA, f"事件 {event_id} 的时间格式非法", event_id)
    modality: str | None = None
    payload: str | None = None
    summary: str | None = None
    if version == 2:
        text = ""
        modality = _string_field(data, "modality")
        if modality not in MODALITIES:
            raise JianError(E_SCHEMA, f"事件 {event_id} 的 modality 非法", event_id)
        payload = _string_field(data, "payload")
        if not PAYLOAD_RE.match(payload):
            raise JianError(E_SCHEMA, f"事件 {event_id} 的 payload 非法", event_id)
        summary = _string_field(data, "summary")
        if not 1 <= len(summary) <= SUMMARY_MAX_CHARS:
            raise JianError(E_SCHEMA, f"事件 {event_id} 的 summary 长度越界", event_id)
    else:
        text = _string_field(data, "text")
        if not 1 <= len(text) <= TEXT_MAX_CHARS:
            raise JianError(E_SCHEMA, f"事件 {event_id} 的 text 长度越界", event_id)
        if event_type == "refusal" and len(text) > REFUSAL_TEXT_MAX_CHARS:
            raise JianError(E_SCHEMA, f"事件 {event_id} 的 text 超过拒绝上限", event_id)
        if event_type == "proposal" and len(text) > PROPOSAL_TEXT_MAX_CHARS:
            raise JianError(E_SCHEMA, f"事件 {event_id} 的 text 超过提案上限", event_id)
    prev = _string_field(data, "prev")
    if not HEX_RE.match(prev):
        raise JianError(E_SCHEMA, f"事件 {event_id} 的 prev 非法", event_id)
    digest = _string_field(data, "hash")
    if not HEX_RE.match(digest):
        raise JianError(E_SCHEMA, f"事件 {event_id} 的 hash 非法", event_id)
    role = _optional_role(data, event_id)
    kind = _optional_kind(data, event_type, event_id)
    trace: str | None = None
    if event_type == "proposal":
        (target, model, prompt_sha,
         quant, weights_sha, temp_milli, seed) = _proposal_fields(data, event_id)
    elif event_type == "refusal":
        target = _string_field(data, "target")
        if target not in REFUSAL_TARGETS:
            raise JianError(E_SCHEMA, f"事件 {event_id} 的 target 非法", event_id)
        trace = _string_field(data, "trace")
        if not TRACE_RE.match(trace):
            raise JianError(E_SCHEMA, f"事件 {event_id} 的 trace 非法", event_id)
        model = None
        prompt_sha = None
        quant = None
        weights_sha = None
        temp_milli = None
        seed = None
    else:
        target = _optional_target(data, event_id)
        model = None
        prompt_sha = None
        quant = None
        weights_sha = None
        temp_milli = None
        seed = None
    return Event(
        version, event_id, segment, stamp, event_type, role, text, prev, digest, kind,
        target, model, prompt_sha, quant, weights_sha, temp_milli, seed,
        modality, payload, summary, trace,
    )


def parse_line(line: str) -> Event:
    """Parse and validate one JSONL line (without its trailing newline)."""
    try:
        data: Any = json.loads(line)
    except json.JSONDecodeError as exc:
        raise JianError(E_SCHEMA, "证据行不是合法 JSON") from exc
    return parse_event(data)


def _validate_fields(
    event_type: Any,
    role: Any,
    text: Any,
    kind: Any,
    target: Any,
    model: Any,
    prompt_sha: Any,
    quant: Any,
    weights_sha: Any,
    temp_milli: Any,
    seed: Any,
    trace: Any,
) -> tuple[
    str, str | None, str | None, str | None, str | None, str | None,
    str | None, str | None, int | None, int | None, str | None,
]:
    if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
        raise JianError(E_SCHEMA, f"未知事件类型：{event_type}")
    if event_type == "proposal":
        limit = PROPOSAL_TEXT_MAX_CHARS
    elif event_type == "refusal":
        limit = REFUSAL_TEXT_MAX_CHARS
    else:
        limit = TEXT_MAX_CHARS
    if not isinstance(text, str) or not 1 <= len(text) <= limit:
        raise JianError(E_SCHEMA, f"text 长度必须是 1-{limit} 字符")
    return _validate_typed_fields(
        event_type, role, kind, target, model, prompt_sha,
        quant, weights_sha, temp_milli, seed, trace,
    )


def _validate_typed_fields(
    event_type: Any,
    role: Any,
    kind: Any,
    target: Any,
    model: Any,
    prompt_sha: Any,
    quant: Any,
    weights_sha: Any,
    temp_milli: Any,
    seed: Any,
    trace: Any,
) -> tuple[
    str, str | None, str | None, str | None, str | None, str | None,
    str | None, str | None, int | None, int | None, str | None,
]:
    """Validate the type-specific fields shared by both envelope versions."""
    if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
        raise JianError(E_SCHEMA, f"未知事件类型：{event_type}")
    required, optional = _TYPE_FIELDS[event_type]
    for name, value in (
        ("role", role), ("kind", kind), ("target", target),
        ("model", model), ("prompt_sha", prompt_sha),
        ("quant", quant), ("weights_sha", weights_sha),
        ("temp_milli", temp_milli), ("seed", seed), ("trace", trace),
    ):
        if value is not None and name not in required and name not in optional:
            raise JianError(E_SCHEMA, f"{event_type} 事件不允许字段 {name}")
    if "role" in required and role not in ROLES:
        raise JianError(E_SCHEMA, "role 只能是 user 或 assistant")
    if "kind" in required:
        if kind not in KIND_VALUES[event_type]:
            raise JianError(E_SCHEMA, f"{event_type} 事件的 kind 非法")
    if event_type == "refusal":
        if target not in REFUSAL_TARGETS:
            raise JianError(E_SCHEMA, f"refusal 事件的 target 非法：{target}")
        if not isinstance(trace, str) or not TRACE_RE.match(trace):
            raise JianError(E_SCHEMA, "refusal 事件的 trace 必须是 sha256:<64 位小写十六进制>")
        return event_type, role, kind, str(target), None, None, None, None, None, None, trace
    if event_type == "proposal":
        checked = _checked_proposal_fields(
            target, model, prompt_sha, quant, weights_sha, temp_milli, seed
        )
        return event_type, role, kind, *checked, None
    if target is not None and not ID_RE.match(str(target)):
        raise JianError(E_SCHEMA, f"target 必须是事件 id：{target}")
    return event_type, role, kind, target, None, None, None, None, None, None, None


def _check_v2_content(modality: Any, payload: Any, summary: Any) -> None:
    """Validate the three required fields of the v2 envelope."""
    if not isinstance(modality, str) or modality not in MODALITIES:
        raise JianError(E_SCHEMA, f"modality 非法：{modality}")
    if not isinstance(payload, str) or not PAYLOAD_RE.match(payload):
        raise JianError(E_SCHEMA, "payload 必须是 sha256:<64 位小写十六进制>")
    if not isinstance(summary, str) or not 1 <= len(summary) <= SUMMARY_MAX_CHARS:
        raise JianError(E_SCHEMA, f"summary 长度必须是 1-{SUMMARY_MAX_CHARS} 字符")


def _checked_proposal_fields(
    target: object,
    model: object,
    prompt_sha: object,
    quant: object,
    weights_sha: object,
    temp_milli: object,
    seed: object,
) -> tuple[str, str, str, str | None, str | None, int | None, int | None]:
    """Return the validated proposal fields; the target whitelist is a gate."""
    for name, value in (("target", target), ("model", model), ("prompt_sha", prompt_sha)):
        if not isinstance(value, str) or not value:
            raise JianError(E_SCHEMA, f"proposal 事件的 {name} 必须是非空字符串")
    if len(str(target)) > MODEL_MAX_CHARS:
        raise JianError(E_SCHEMA, "proposal 事件的 target 过长")
    if len(str(model)) > MODEL_MAX_CHARS:
        raise JianError(E_SCHEMA, "proposal 事件的 model 过长")
    if not PROMPT_SHA_RE.match(str(prompt_sha)):
        raise JianError(E_SCHEMA, "proposal 事件的 prompt_sha 必须是十六进制")
    if quant is not None:
        if not isinstance(quant, str) or not 1 <= len(quant) <= QUANT_MAX_CHARS:
            raise JianError(E_SCHEMA, "proposal 事件的 quant 必须是 1-32 字符")
    if weights_sha is not None:
        if not isinstance(weights_sha, str) or not WEIGHTS_SHA_RE.match(weights_sha):
            raise JianError(E_SCHEMA, "proposal 事件的 weights_sha 必须是 1-64 位十六进制")
    if temp_milli is not None:
        if isinstance(temp_milli, bool) or not isinstance(temp_milli, int):
            raise JianError(E_SCHEMA, "proposal 事件的 temp_milli 必须是整数")
        if not TEMP_MILLI_MIN <= temp_milli <= TEMP_MILLI_MAX:
            raise JianError(E_SCHEMA, "proposal 事件的 temp_milli 必须在 0-2000")
    if seed is not None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise JianError(E_SCHEMA, "proposal 事件的 seed 必须是整数")
        if not SEED_MIN <= seed <= SEED_MAX:
            raise JianError(E_SCHEMA, "proposal 事件的 seed 必须在 0 <= seed < 2^31")
    return (
        str(target), str(model), str(prompt_sha),
        None if quant is None else str(quant),
        None if weights_sha is None else str(weights_sha),
        temp_milli if isinstance(temp_milli, int) and not isinstance(temp_milli, bool) else None,
        seed if isinstance(seed, int) and not isinstance(seed, bool) else None,
    )


def _proposal_fields(
    data: dict[str, object], event_id: str
) -> tuple[str, str, str, str | None, str | None, int | None, int | None]:
    """Read the proposal fields; empty strings stay valid for the G5 gate."""
    target = _string_field(data, "target")
    model = _string_field(data, "model")
    prompt_sha = _string_field(data, "prompt_sha")
    if len(target) > MODEL_MAX_CHARS or len(model) > MODEL_MAX_CHARS:
        raise JianError(E_SCHEMA, f"事件 {event_id} 的提案字段过长", event_id)
    if len(prompt_sha) > PROMPT_SHA_MAX_CHARS:
        raise JianError(E_SCHEMA, f"事件 {event_id} 的 prompt_sha 过长", event_id)
    if prompt_sha and not PROMPT_SHA_RE.match(prompt_sha):
        raise JianError(E_SCHEMA, f"事件 {event_id} 的 prompt_sha 非十六进制", event_id)
    quant = _optional_text(data, "quant", QUANT_MAX_CHARS, event_id)
    weights_sha = _optional_text(
        data, "weights_sha", WEIGHTS_SHA_MAX_CHARS, event_id
    )
    if weights_sha is not None and not WEIGHTS_SHA_RE.match(weights_sha):
        raise JianError(E_SCHEMA, f"事件 {event_id} 的 weights_sha 非十六进制", event_id)
    temp_milli = _optional_int(
        data, "temp_milli", TEMP_MILLI_MIN, TEMP_MILLI_MAX, event_id
    )
    seed = _optional_int(data, "seed", SEED_MIN, SEED_MAX, event_id)
    return target, model, prompt_sha, quant, weights_sha, temp_milli, seed


def _optional_text(
    data: dict[str, object], name: str, limit: int, event_id: str
) -> str | None:
    """Return a bounded optional string field, or None when it is absent."""
    if name not in data:
        return None
    value = _string_field(data, name)
    if not 1 <= len(value) <= limit:
        raise JianError(E_SCHEMA, f"事件 {event_id} 的 {name} 长度越界", event_id)
    return value


def _optional_int(
    data: dict[str, object], name: str, low: int, high: int, event_id: str
) -> int | None:
    """Return a bounded optional integer field, or None when it is absent."""
    if name not in data:
        return None
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise JianError(E_SCHEMA, f"事件 {event_id} 的 {name} 必须是整数", event_id)
    if not low <= value <= high:
        raise JianError(E_SCHEMA, f"事件 {event_id} 的 {name} 越界", event_id)
    return value


def _optional_role(data: dict[str, object], event_id: str) -> str | None:
    if "role" not in data:
        return None
    role = _string_field(data, "role")
    if role not in ROLES:
        raise JianError(E_SCHEMA, f"事件 {event_id} 的 role 非法", event_id)
    return role


def _optional_kind(data: dict[str, object], event_type: str, event_id: str) -> str | None:
    if "kind" not in data:
        return None
    kind = _string_field(data, "kind")
    if kind not in KIND_VALUES.get(event_type, ()):
        raise JianError(E_SCHEMA, f"事件 {event_id} 的 kind 非法", event_id)
    return kind


def _optional_target(data: dict[str, object], event_id: str) -> str | None:
    if "target" not in data:
        return None
    target = _string_field(data, "target")
    if not ID_RE.match(target):
        raise JianError(E_SCHEMA, f"事件 {event_id} 的 target 非法", event_id)
    return target


def _string_field(data: dict[str, object], name: str) -> str:
    value = data[name]
    if not isinstance(value, str):
        raise JianError(E_SCHEMA, f"{name} 必须是字符串")
    return value
