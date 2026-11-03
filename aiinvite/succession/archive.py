"""Zip, JSON and evidence primitives for legacy capsules (M15)."""

from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Mapping, Sequence

from aiinvite.canonical import dumps
from aiinvite.chain import (
    Segment,
    chain_document,
    parse_chain,
    read_blob,
    summarize,
    verify_evidence,
)
from aiinvite.errors import AiInviteError
from aiinvite.event import SEG_RE, Event, parse_line
from aiinvite.kernel.kernel import Policy

from aiinvite.succession.errors import (
    E_SUCC_HEADER,
    E_SUCC_IO,
    E_SUCC_SCHEMA,
    SuccessionError,
)
from aiinvite.succession.model import (
    BLOB_RE,
    BLOBS_DIR,
    CHAIN_PATH,
    EVIDENCE_DIR,
    EVIDENCE_RE,
    LETTER_RE,
    MANIFEST_PATH,
    POLICY_PATH,
    REDACTION_PATH,
    REVIVAL_PATH,
    SUCCESSION_PATH,
    digest,
    recompute_kid,
)

ZIP_DATE = (1980, 1, 1, 0, 0, 0)
META_PATHS = (CHAIN_PATH, REVIVAL_PATH, POLICY_PATH, REDACTION_PATH, SUCCESSION_PATH)


def read_zip(path: Path) -> dict[str, bytes]:
    """Read every entry of a capsule, rejecting directories and duplicates."""
    try:
        with zipfile.ZipFile(path, "r") as archive:
            entries: dict[str, bytes] = {}
            for info in archive.infolist():
                if info.is_dir():
                    raise SuccessionError(E_SUCC_HEADER, "胶囊不应包含目录条目")
                if info.filename in entries:
                    raise SuccessionError(E_SUCC_HEADER, "胶囊包含重复条目")
                entries[info.filename] = archive.read(info.filename)
            return entries
    except (OSError, zipfile.BadZipFile) as error:
        raise SuccessionError(E_SUCC_IO, f"无法读取胶囊：{path}") from error


def write_zip(entries: Mapping[str, bytes], out: Path) -> None:
    """Write a byte-reproducible torrent-free zip (STORE, fixed order/time)."""
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
            for name in sorted(entries):
                info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                info.external_attr = 0o644 << 16
                info.extra = b""
                archive.writestr(info, entries[name])
    except OSError as error:
        raise SuccessionError(E_SUCC_IO, f"写入胶囊失败：{out}") from error


def read_bytes(path: Path) -> bytes:
    """Read one file, mapping ``OSError`` to ``E_SUCC_IO``."""
    try:
        return path.read_bytes()
    except OSError as error:
        raise SuccessionError(E_SUCC_IO, f"读取失败：{path}") from error


def write_bytes(path: Path, data: bytes) -> None:
    """Write one file, creating parents and mapping ``OSError``."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError as error:
        raise SuccessionError(E_SUCC_IO, f"写入失败：{path}") from error


def decode_json(blob: bytes, name: str, code: str) -> dict[str, object]:
    """Decode one JSON object entry, raising ``code`` on any malformation."""
    try:
        data = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SuccessionError(code, f"{name} 解码失败") from error
    if not isinstance(data, dict):
        raise SuccessionError(code, f"{name} 必须是对象")
    return data


def require(entries: Mapping[str, bytes], name: str) -> bytes:
    """Return one required entry or raise ``E_SUCC_HEADER``."""
    data = entries.get(name)
    if data is None:
        raise SuccessionError(E_SUCC_HEADER, f"legacy 胶囊缺少 {name}")
    return data


def entry_kind(name: str) -> str | None:
    """Return ``meta`` / ``evidence`` / ``blob`` / ``letter`` or None."""
    if name in META_PATHS:
        return "meta"
    if EVIDENCE_RE.match(name):
        return "evidence"
    if BLOB_RE.match(name):
        return "blob"
    if LETTER_RE.match(name):
        return "letter"
    return None


def evidence_entries(entries: Mapping[str, bytes]) -> dict[str, bytes]:
    """Collect the evidence segments of a capsule keyed by segment name."""
    evidence: dict[str, bytes] = {}
    for name, data in entries.items():
        match = EVIDENCE_RE.match(name)
        if match is None:
            continue
        key = match.group(1)
        if not SEG_RE.match(key) or key in evidence:
            raise SuccessionError(E_SUCC_HEADER, f"非法证据文件名：{name}")
        evidence[key] = data
    if not evidence:
        raise SuccessionError(E_SUCC_HEADER, "legacy 胶囊缺少证据段")
    return evidence


def read_evidence_bytes(store: Path) -> dict[str, bytes]:
    """Read every ``evidence/seg-NNNN.jsonl`` of a store."""
    folder = store / EVIDENCE_DIR
    if not folder.is_dir():
        raise SuccessionError(E_SUCC_IO, "缺少 evidence 目录")
    result: dict[str, bytes] = {}
    for path in sorted(folder.glob("seg-*.jsonl")):
        name = path.name[: -len(".jsonl")]
        if not SEG_RE.match(name) or name in result:
            raise SuccessionError(E_SUCC_HEADER, f"非法证据文件名：{path.name}")
        result[name] = read_bytes(path)
    if not result:
        raise SuccessionError(E_SUCC_HEADER, "证据目录为空")
    return result


def read_events(store: Path) -> list[Event]:
    """Parse every evidence event of a store in file order."""
    events: list[Event] = []
    for _, data in sorted(read_evidence_bytes(store).items()):
        for line in data.decode("utf-8").split("\n")[:-1]:
            if line:
                events.append(parse_line(line))
    return events


def read_chain(store: Path) -> dict[str, object]:
    """Read and validate ``chain.json`` from a store."""
    path = store / CHAIN_PATH
    if not path.is_file():
        raise SuccessionError(E_SUCC_HEADER, "缺少 chain.json")
    try:
        data = json.loads(read_bytes(path).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SuccessionError(E_SUCC_HEADER, "chain.json 解码失败") from error
    try:
        return parse_chain(data)
    except AiInviteError as error:
        raise SuccessionError(E_SUCC_HEADER, f"chain.json 非法：{error}") from error


def evidence_digest(evidence: Mapping[str, bytes]) -> str:
    """Bind an evidence set to one digest (used by ``redaction.json``)."""
    payload = dumps({
        "files": [
            {"path": f"{EVIDENCE_DIR}/{name}.jsonl", "sha256": digest(data)}
            for name, data in sorted(evidence.items())
        ],
    })
    return hashlib.sha256(payload).hexdigest()


def count_events(evidence: Mapping[str, bytes]) -> int:
    """Count evidence lines across all shipped segments."""
    return sum(
        len(data.decode("utf-8").split("\n")) - 1 for data in evidence.values()
    )


def segments_from_chain(chain: Mapping[str, object]) -> list[Segment]:
    """Rebuild ``Segment`` objects from a decoded ``chain.json``."""
    rows = chain["segments"]
    return [
        Segment(
            str(row["seg"]), int(row["count"]), str(row["first"]),
            str(row["last"]), row["prev_seg"],
        )
        for row in rows
    ]


def segments_from_groups(groups: Mapping[str, Sequence[Event]]) -> list[Segment]:
    """Build ``Segment`` objects from events grouped by segment name."""
    segments: list[Segment] = []
    previous: str | None = None
    for name in sorted(groups):
        rows = groups[name]
        segments.append(Segment(name, len(rows), rows[0].hash, rows[-1].hash, previous))
        previous = name
    return segments


def blob_list(events: Sequence[Event]) -> list[str] | None:
    """Return the sorted payload digests of a v2 evidence set, else None."""
    if not events:
        return None
    versions = {event.v for event in events}
    if len(versions) > 1:
        raise SuccessionError(E_SUCC_SCHEMA, "同一证据集不允许混写 v1 与 v2")
    if versions != {2}:
        return None
    return sorted({str(event.payload).split(":", 1)[1] for event in events})


def blob_map(store: Path, events: Sequence[Event]) -> dict[str, bytes] | None:
    """Read every referenced blob from a store."""
    digests = blob_list(events)
    if digests is None:
        return None
    return {item: read_blob(store, item) for item in digests}


def blob_map_from_entries(
    entries: Mapping[str, bytes], events: Sequence[Event]
) -> dict[str, bytes] | None:
    """Check capsule blob entries against the payloads the evidence references."""
    digests = blob_list(events)
    found = {match.group(1) for name in entries for match in [BLOB_RE.match(name)] if match}
    if digests is None:
        if found:
            raise SuccessionError(E_SUCC_HEADER, f"胶囊含未登记载荷：{sorted(found)[0]}")
        return None
    extra = found - set(digests)
    if extra:
        raise SuccessionError(E_SUCC_HEADER, f"胶囊含未登记载荷：{sorted(extra)[0]}")
    result: dict[str, bytes] = {}
    for item in digests:
        data = entries.get(f"{BLOBS_DIR}/{item}")
        if data is None:
            raise SuccessionError(E_SUCC_HEADER, f"胶囊缺少载荷：{item}")
        if digest(data) != item:
            raise SuccessionError(E_SUCC_HEADER, f"载荷内容与哈希不符：{item}")
        result[item] = data
    return result


def verify_evidence_set(
    evidence: Mapping[str, bytes],
) -> tuple[int, str, list[Segment], list[Event]]:
    """Verify canonical bytes and the hash chain of an evidence mapping."""
    parsed: list[tuple[str, list[Event]]] = []
    for name in sorted(evidence):
        try:
            text = evidence[name].decode("utf-8")
        except UnicodeDecodeError as error:
            raise SuccessionError(E_SUCC_SCHEMA, f"段 {name} 不是 UTF-8") from error
        if not text.endswith("\n"):
            raise SuccessionError(E_SUCC_SCHEMA, f"段 {name} 未以换行结尾")
        rows: list[Event] = []
        for line in text.split("\n")[:-1]:
            if not line:
                raise SuccessionError(E_SUCC_SCHEMA, f"段 {name} 含空行")
            event = parse_line(line)
            if line.encode("utf-8") != dumps(event.as_dict()):
                raise SuccessionError(E_SUCC_SCHEMA, f"事件 {event.id} 不是规范字节")
            rows.append(event)
        parsed.append((name, rows))
    try:
        count, head = verify_evidence(parsed)
        segments = summarize(parsed)
    except AiInviteError as error:
        raise SuccessionError(E_SUCC_SCHEMA, f"证据链无效：{error}") from error
    events = [event for _, rows in parsed for event in rows]
    return count, head, segments, events


def compile_evidence(
    evidence: Mapping[str, bytes], blobs: Mapping[str, bytes] | None, policy: Policy
) -> str:
    """Compile an in-memory evidence set by materializing a temporary store."""
    with tempfile.TemporaryDirectory(prefix="aiinvite_legacy_") as folder:
        root = Path(folder)
        target = root / EVIDENCE_DIR
        target.mkdir()
        for name, data in evidence.items():
            write_bytes(target / f"{name}.jsonl", data)
        if blobs:
            blob_root = root / BLOBS_DIR
            blob_root.mkdir()
            for item, data in blobs.items():
                write_bytes(blob_root / item, data)
        return recompute_kid(root, policy)


def chain_bytes(sealed_at: str, segments: Sequence[Segment],
                blobs: Sequence[str] | None) -> bytes:
    """Render ``chain.json`` bytes for a legacy capsule."""
    return dumps(chain_document(sealed_at, segments, blobs))


def revival_text(segments: int, head: str, sealed_at: str) -> str:
    """Return the human-readable revival guide shipped in the capsule."""
    return "\n".join([
        "# AI Invite legacy capsule revival guide",
        "",
        f"segments: {segments}",
        f"head: {head}",
        f"sealed_at: {sealed_at}",
        "",
        "## Layout",
        "- manifest.json: format, created, kid, policy_digest, head, files",
        "- chain.json / evidence/: the same hash chain as a normal capsule",
        "- policy.json: the exact compilation policy; without it kid changes",
        "- redaction.json: excluded ids, reasons, origin_kid, redacted_kid",
        "- succession.json: successor_kid, derived_from, redacted, mode",
        "- letters/: optional plain-text notes",
        "",
        "## Verify without this code",
        "1. Check every manifest.files sha256 and byte count.",
        "2. Rebuild each event body without hash; check sha256(prev + LF + body).",
        "3. Recompile with policy.json; the kid must equal manifest.kid.",
        "4. If redaction.json lists excluded ids, the kid must differ from origin_kid.",
        "",
    ])


def manifest_document(
    created: str, kid: str, policy_data: bytes, head: str,
    files: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Build the legacy ``manifest.json`` object."""
    from aiinvite.succession.model import FORMAT_VERSION, LEGACY_FORMAT

    return {
        "format": LEGACY_FORMAT,
        "format_version": FORMAT_VERSION,
        "created": created,
        "kid": kid,
        "policy_digest": digest(policy_data),
        "head": head,
        "files": list(files),
        "signature": None,
    }


def entry_kind_is_legal(name: str) -> bool:
    """Return whether ``name`` is one of the legacy capsule entry kinds."""
    return entry_kind(name) is not None or name == MANIFEST_PATH
