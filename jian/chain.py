"""Hash chain construction and verification."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .canonical import _encode_string
from .errors import (
    E_BLOB_MISMATCH,
    E_BLOB_MISSING,
    E_CHAIN_MISSING,
    E_HEADER_MISMATCH,
    E_IO,
    E_SCHEMA,
    E_TAMPER,
    JianError,
)
from .event import (
    GENESIS_PREV,
    SEGMENT_MAX_EVENTS,
    TEXT_MAX_CHARS,
    Event,
    event_digest,
    format_id,
)

_SEG_NAME_RE = re.compile(r"^seg-([0-9]{4})$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
BLOBS_DIR = "blobs"
BLOB_RE = re.compile(r"^blobs/([0-9a-f]{64})$")
_EVENT_HEAD_RE = (
    r'^\{"ep":"seg-[0-9]{4}",'
    r'"hash":"[0-9a-f]{64}",'
    r'"id":"ev_[0-9]{6}",'
    r'"prev":"[0-9a-f]{64}",'
    r'"role":"(?:user|assistant)",'
    r'"t":"[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])'
    r'T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z",'
    r'"text":'
)
_EVENT_TAIL_RE = r',"type":"turn","v":1\}$'
_EVENT_TAIL_TEXT = ',"type":"turn","v":1}'
_EVENT_PLAIN_RE = re.compile(_EVENT_HEAD_RE + r'"[^"\\\x00-\x1f]*"' + _EVENT_TAIL_RE)
_EVENT_ESCAPED_RE = re.compile(
    _EVENT_HEAD_RE + r'"(?:[^"\\\x00-\x1f]|\\["\\]|\\u00[0-9a-f]{2})*"' + _EVENT_TAIL_RE
)


class _FastPathMiss(Exception):
    """Signal that canonical fast scanning cannot handle this evidence."""


@dataclass(frozen=True)
class Segment:
    """Summary of one evidence segment."""

    seg: str
    count: int
    first: str
    last: str
    prev_seg: str | None

    def as_dict(self) -> dict[str, object]:
        """Return the chain.json representation of this segment."""
        return {
            "seg": self.seg,
            "count": self.count,
            "first": self.first,
            "last": self.last,
            "prev_seg": self.prev_seg,
        }


def segment_number(name: str) -> int:
    """Return the numeric index of a ``seg-NNNN`` name."""
    match = _SEG_NAME_RE.match(name)
    if not match:
        raise JianError(E_CHAIN_MISSING, f"非法段名：{name}")
    return int(match.group(1))


def summarize(evidence: Sequence[tuple[str, Sequence[Event]]]) -> list[Segment]:
    """Build segment summaries from parsed evidence in order."""
    segments: list[Segment] = []
    previous: str | None = None
    for name, events in evidence:
        if not events:
            raise JianError(E_CHAIN_MISSING, f"段 {name} 没有事件")
        segments.append(Segment(name, len(events), events[0].hash, events[-1].hash, previous))
        previous = name
    return segments


def verify_evidence(evidence: Sequence[tuple[str, Sequence[Event]]]) -> tuple[int, str]:
    """Verify ids, links and hashes across all segments.

    Returns ``(event_count, head_hash)``. Raises ``E_CHAIN_MISSING`` for a
    broken or missing link and ``E_TAMPER`` (with the event id) for content
    that no longer matches its hash.
    """
    if not evidence:
        raise JianError(E_CHAIN_MISSING, "没有证据段")
    expected_prev = GENESIS_PREV
    expected_seq = 1
    expected_index = 1
    for name, events in evidence:
        index = segment_number(name)
        if index != expected_index:
            raise JianError(E_CHAIN_MISSING, f"缺少段：期望 seg-{expected_index:04d}")
        if not events:
            raise JianError(E_CHAIN_MISSING, f"段 {name} 是空的")
        if len(events) > SEGMENT_MAX_EVENTS:
            raise JianError(E_SCHEMA, f"段 {name} 超过 {SEGMENT_MAX_EVENTS} 条事件")
        for event in events:
            if event.ep != name:
                raise JianError(E_SCHEMA, f"事件 {event.id} 的段名与文件不符", event.id)
            if event.id != format_id(expected_seq):
                raise JianError(E_CHAIN_MISSING, f"事件 {event.id} 序号不连续", event.id)
            if event.prev != expected_prev:
                raise JianError(E_CHAIN_MISSING, f"事件 {event.id} 的 prev 不接上一条", event.id)
            if event_digest(event) != event.hash:
                raise JianError(E_TAMPER, f"事件 {event.id} 内容与 hash 不符", event.id)
            expected_prev = event.hash
            expected_seq += 1
        expected_index += 1
    return expected_seq - 1, expected_prev


def chain_document(sealed_at: str | None, segments: Sequence[Segment],
                   blobs: Sequence[str] | None = None) -> dict[str, object]:
    """Build the chain.json document for the given segments.

    ``blobs`` is omitted for v1 stores and carries the sorted payload digests
    for v2 stores.
    """
    document: dict[str, object] = {
        "v": 1,
        "sealed_at": sealed_at,
        "segments": [segment.as_dict() for segment in segments],
    }
    if blobs is not None:
        document["blobs"] = list(blobs)
    return document


def chain_matches(document: Mapping[str, object], sealed_at: str | None,
                  segments: Sequence[Segment],
                  blobs: Sequence[str] | None = None) -> bool:
    """Return whether a decoded chain.json equals the recomputed chain."""
    return dict(document) == chain_document(sealed_at, segments, blobs)


def parse_chain(data: object) -> dict[str, object]:
    """Validate a decoded chain.json document and return it."""
    if not isinstance(data, dict):
        raise JianError(E_SCHEMA, "chain.json 必须是对象")
    if set(data) == {"v", "sealed_at", "segments"}:
        has_blobs = False
    elif set(data) == {"v", "sealed_at", "segments", "blobs"}:
        has_blobs = True
    else:
        raise JianError(E_SCHEMA, "chain.json 字段缺失或多余")
    if isinstance(data["v"], bool) or not isinstance(data["v"], int) or data["v"] != 1:
        raise JianError(E_SCHEMA, "chain.json 的 v 必须为 1")
    sealed_at = data["sealed_at"]
    if sealed_at is not None and not isinstance(sealed_at, str):
        raise JianError(E_SCHEMA, "chain.json 的 sealed_at 必须是字符串或 null")
    rows = data["segments"]
    if not isinstance(rows, list):
        raise JianError(E_SCHEMA, "chain.json 的 segments 必须是数组")
    for row in rows:
        _validate_segment_row(row)
    if has_blobs:
        _validate_blob_list(data["blobs"])
    return data


def _validate_blob_list(value: object) -> None:
    if not isinstance(value, list):
        raise JianError(E_SCHEMA, "chain.json 的 blobs 必须是数组")
    names = []
    for item in value:
        if not isinstance(item, str) or not _HEX64_RE.match(item):
            raise JianError(E_SCHEMA, "chain.json 的 blobs 条目非法")
        names.append(item)
    if names != sorted(names) or len(set(names)) != len(names):
        raise JianError(E_SCHEMA, "chain.json 的 blobs 未严格升序或含重复")


def _validate_segment_row(row: object) -> None:
    if not isinstance(row, dict):
        raise JianError(E_SCHEMA, "chain.json 的段条目必须是对象")
    if set(row) != {"seg", "count", "first", "last", "prev_seg"}:
        raise JianError(E_SCHEMA, "chain.json 的段条目字段缺失或多余")
    if not isinstance(row["seg"], str) or not _SEG_NAME_RE.match(row["seg"]):
        raise JianError(E_SCHEMA, "chain.json 的段名非法")
    count = row["count"]
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 100:
        raise JianError(E_SCHEMA, "chain.json 的 count 越界")
    for key in ("first", "last"):
        value = row[key]
        if not isinstance(value, str) or len(value) != 64:
            raise JianError(E_SCHEMA, f"chain.json 的 {key} 非法")
    prev_seg = row["prev_seg"]
    if prev_seg is not None and (
        not isinstance(prev_seg, str) or not _SEG_NAME_RE.match(prev_seg)
    ):
        raise JianError(E_SCHEMA, "chain.json 的 prev_seg 非法")


def put_blob(store: Path, data: bytes) -> str:
    """Write ``data`` under ``store/blobs/<sha256>`` and return the digest.

    Writes are content addressed and append only: the same bytes create the
    same file once, and an existing file is re-verified instead of overwritten.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise JianError(E_SCHEMA, "载荷必须是 bytes")
    payload = bytes(data)
    digest = _sha256(payload)
    path = store / BLOBS_DIR / digest
    if path.is_file():
        if _sha256(_read_bytes(path)) != digest:
            raise JianError(E_BLOB_MISMATCH, f"载荷内容与其哈希不符：{digest}")
        return digest
    _write_bytes(path, payload)
    if _sha256(_read_bytes(path)) != digest:
        raise JianError(E_BLOB_MISMATCH, f"载荷写入后校验失败：{digest}")
    return digest


def read_blob(store: Path, digest: str) -> bytes:
    """Return the bytes stored under ``blobs/<digest>`` after verifying them."""
    if not isinstance(digest, str) or not _HEX64_RE.match(digest):
        raise JianError(E_SCHEMA, f"非法载荷哈希：{digest}")
    path = store / BLOBS_DIR / digest
    if not path.is_file():
        raise JianError(E_BLOB_MISSING, f"引用的载荷不存在：{digest}")
    data = _read_bytes(path)
    if _sha256(data) != digest:
        raise JianError(E_BLOB_MISMATCH, f"载荷内容与其哈希不符：{digest}")
    return data


def _blob_digests(events: Sequence[Event] | None) -> list[str] | None:
    """Return the sorted payload digests of a v2 evidence set, else None."""
    if not events:
        return None
    versions = {event.v for event in events}
    if len(versions) > 1:
        raise JianError(E_SCHEMA, "同一 store 不允许混写 v1 与 v2 事件")
    if versions != {2}:
        return None
    refs = sorted({str(event.payload) for event in events})
    return [ref.split(":", 1)[1] for ref in refs]


def _check_capsule_blobs(entries: Mapping[str, bytes], digests: Sequence[str]) -> None:
    """Require every referenced blob in a capsule and reject unregistered ones."""
    expected = {f"{BLOBS_DIR}/{digest}" for digest in digests}
    found = {name for name in entries if BLOB_RE.match(name)}
    extra = found - expected
    if extra:
        raise JianError(E_HEADER_MISMATCH, f"胶囊含未登记的载荷：{sorted(extra)[0]}")
    for digest in digests:
        name = f"{BLOBS_DIR}/{digest}"
        if name not in entries:
            raise JianError(E_BLOB_MISSING, f"胶囊缺少载荷：{digest}")
        if _sha256(entries[name]) != digest:
            raise JianError(E_BLOB_MISMATCH, f"载荷内容与其哈希不符：{digest}")


def _scan_canonical(evidence: Mapping[str, bytes]) -> tuple[int, str, list[Segment]]:
    """Verify evidence with a canonical-layout scanner.

    Each line is matched against the fixed canonical event layout; the hashed
    body is then the line with its ``"hash"`` field sliced out (positions are
    fixed because every other field has a fixed width). Lines outside that
    layout raise ``_FastPathMiss`` so the strict parser handles them.
    """
    expected_prev = GENESIS_PREV
    expected_seq = 1
    expected_index = 1
    previous_seg: str | None = None
    segments: list[Segment] = []
    for name in sorted(evidence):
        if segment_number(name) != expected_index:
            raise JianError(E_CHAIN_MISSING, f"缺少段：期望 seg-{expected_index:04d}")
        try:
            text = evidence[name].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise JianError(E_SCHEMA, f"段 {name} 不是 UTF-8 编码") from exc
        if not text.endswith("\n"):
            raise JianError(E_SCHEMA, f"段 {name} 未以换行结尾")
        lines = text.split("\n")[:-1]
        if not lines:
            raise JianError(E_CHAIN_MISSING, f"段 {name} 是空的")
        if len(lines) > SEGMENT_MAX_EVENTS:
            raise JianError(E_SCHEMA, f"段 {name} 超过 {SEGMENT_MAX_EVENTS} 条事件")
        first_hash: str | None = None
        last_hash = ""
        for line in lines:
            match = _EVENT_PLAIN_RE.match(line)
            plain = match is not None
            if not plain:
                match = _EVENT_ESCAPED_RE.match(line)
            if match is None:
                raise _FastPathMiss()
            if "seg-" + line[11:15] != name:
                raise _FastPathMiss()
            seq_text = line[100:106]
            if int(seq_text) != expected_seq:
                raise JianError(
                    E_CHAIN_MISSING, f"事件序号不连续：ev_{seq_text}", f"ev_{seq_text}"
                )
            prev = line[116:180]
            if prev != expected_prev:
                raise JianError(
                    E_CHAIN_MISSING, f"事件 ev_{seq_text} 的 prev 不接上一条", f"ev_{seq_text}"
                )
            text_start = line.find('"text":') + 7
            raw_text = line[text_start:-len(_EVENT_TAIL_TEXT)]
            text_body = raw_text[1:-1]
            if not 1 <= len(text_body) <= TEXT_MAX_CHARS:
                raise _FastPathMiss()
            if not (plain and text_body.isascii()):
                try:
                    decoded = json.loads(raw_text)
                except json.JSONDecodeError:
                    raise _FastPathMiss()
                if (not isinstance(decoded, str)
                        or not 1 <= len(decoded) <= TEXT_MAX_CHARS
                        or _encode_string(decoded) != raw_text):
                    raise _FastPathMiss()
            body = line[:17] + line[91:]
            digest = hashlib.sha256(
                expected_prev.encode("ascii") + b"\n" + body.encode("utf-8")
            ).hexdigest()
            if digest != line[25:89]:
                raise JianError(
                    E_TAMPER, f"事件 ev_{seq_text} 内容与 hash 不符", f"ev_{seq_text}"
                )
            if first_hash is None:
                first_hash = digest
            last_hash = digest
            expected_prev = digest
            expected_seq += 1
        segments.append(Segment(name, len(lines), first_hash or "", last_hash, previous_seg))
        previous_seg = name
        expected_index += 1
    return expected_seq - 1, expected_prev, segments


def _render_revival(count: int, segments: Sequence[Segment], head: str,
                    sealed_at: str, blobs: Sequence[str] | None = None) -> str:
    if blobs is not None:
        return _render_revival_v2(count, segments, head, sealed_at, blobs)
    lines = [
        "# Jian capsule revival guide",
        "",
        f"events: {count}",
        f"segments: {len(segments)}",
        f"head: {head}",
        f"sealed_at: {sealed_at}",
        "",
        "## Event fields",
        "- v: always 1",
        "- id: ev_ + six decimal digits, globally increasing",
        "- ep: segment name such as seg-0001",
        "- t: UTC timestamp YYYY-MM-DDTHH:MM:SSZ",
        "- type: turn, feedback, directive, milestone or checkpoint",
        "- role: user or assistant (turn only; forbidden for other types)",
        "- kind: praise or correction (feedback), lock/unlock/rule (directive)",
        "- target: optional event id, feedback only",
        "- text: 1-8000 characters",
        "- prev: hash of the previous event; 64 zeros for the first event",
        "- hash: sha256(prev_ascii + LF + canonical_json_without_hash)",
        "",
        "## Revival without this code (five steps, standard library only)",
        "1. Open memory.aiem with zipfile and read every evidence/seg-*.jsonl entry.",
        "2. Read each line in file order and parse it with json.loads.",
        "3. Rebuild the body by dropping hash, sorting keys, using no spaces, UTF-8.",
        "4. Check sha256(prev.encode('ascii') + b'\\n' + body) == hash and prev == last hash.",
        "5. Append text in event order; stop on the first mismatch and report that id.",
        "",
    ]
    return "\n".join(lines)


def _render_revival_v2(count: int, segments: Sequence[Segment], head: str,
                       sealed_at: str, blobs: Sequence[str]) -> str:
    lines = [
        "# Jian capsule revival guide (envelope v2)",
        "",
        f"events: {count}",
        f"segments: {len(segments)}",
        f"blobs: {len(blobs)}",
        f"head: {head}",
        f"sealed_at: {sealed_at}",
        "",
        "## Envelope v2 fields",
        "- v: always 2",
        "- id: ev_ + six decimal digits, globally increasing",
        "- ep: segment name such as seg-0001",
        "- t: UTC timestamp YYYY-MM-DDTHH:MM:SSZ",
        "- type: turn, feedback, directive, milestone, checkpoint or proposal",
        "- modality: text, audio, vision, action or sensor",
        "- payload: sha256:<64 lowercase hex>; bytes live at blobs/<64 hex>",
        "- summary: 1-200 characters; the only text retrieval may use",
        "- role/kind/target and proposal fields: same per-type rules as v1",
        "- text: forbidden in v2",
        "- prev: hash of the previous event; 64 zeros for the first event",
        "- hash: sha256(prev_ascii + LF + canonical_json_without_hash)",
        "",
        "## Payload rules",
        "1. Every blobs/<hex> file must hash to <hex>; a mismatch means tampering.",
        "2. The chain blobs list must equal the sorted set referenced by events.",
        "3. Retrieval reads summary only and never opens blobs/.",
        "",
        "## Revival without this code (standard library only)",
        "1. Open memory.aiem with zipfile and read every entry.",
        "2. Rebuild each event body by dropping hash, sorting keys, no spaces, UTF-8.",
        "3. Check sha256(prev.encode('ascii') + b'\\n' + body) == hash and prev == last hash.",
        "4. Check sha256(content of blobs/<hex>) == <hex> for every referenced digest.",
        "5. Index summaries in event order; stop on the first mismatch and report that id.",
        "",
    ]
    return "\n".join(lines)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise JianError(E_IO, f"读取失败：{path}") from exc


def _write_bytes(path: Path, data: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as exc:
        raise JianError(E_IO, f"写入失败：{path}") from exc
