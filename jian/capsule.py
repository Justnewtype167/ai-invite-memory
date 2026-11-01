"""Capsule packaging, verification, export and import (M1)."""

from __future__ import annotations

import json
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .canonical import dumps
from .chain import (
    BLOBS_DIR,
    BLOB_RE,
    Segment,
    _FastPathMiss,
    _blob_digests,
    _check_capsule_blobs,
    _read_bytes,
    _render_revival,
    _scan_canonical,
    _sha256,
    _write_bytes,
    chain_document,
    chain_matches,
    parse_chain,
    put_blob,
    read_blob,
    summarize,
    verify_evidence,
)
from .errors import (
    E_CHAIN_MISSING,
    E_HEADER_MISMATCH,
    E_IO,
    E_NOT_CANONICAL,
    E_SCHEMA,
    JianError,
)
from .event import (
    GENESIS_PREV,
    SEGMENT_MAX_EVENTS,
    SEG_RE,
    Event,
    new_event,
    parse_event,
    parse_line,
    utc_now,
)
CAPSULE_SCHEMA = "jian.capsule/1"
EVIDENCE_DIR = "evidence"
CHAIN_PATH = "chain.json"
MANIFEST_PATH = "manifest.json"
REVIVAL_PATH = "REVIVAL.md"

_EVIDENCE_RE = re.compile(r"^evidence/(seg-[0-9]{4})\.jsonl$")

_MANIFEST_KEYS = {
    "capsule_version",
    "schema",
    "created",
    "hash_algo",
    "head",
    "files",
    "signature",
}
_MANIFEST_KEYS_V2 = _MANIFEST_KEYS | {"format", "blob_count"}


@dataclass(frozen=True)
class Verification:
    """Outcome of verifying a store directory or a capsule file."""

    events: int
    segments: int
    head: str
    state: str


@dataclass(frozen=True)
class CapsuleInfo:
    """Metadata read from a capsule without full verification."""

    schema: str
    version: int
    created: str
    head: str
    events: int
    segments: int
    files: int


def init_store(store: Path) -> None:
    """Create an empty unsealed store directory."""
    if store.exists():
        if not store.is_dir():
            raise JianError(E_IO, f"路径不是目录：{store}")
        if any(store.iterdir()):
            raise JianError(E_IO, f"目录已存在且非空：{store}")
    (store / EVIDENCE_DIR).mkdir(parents=True, exist_ok=True)
    _write_bytes(store / CHAIN_PATH, dumps(chain_document(None, [])))


def append_event(
    store: Path,
    role: str | None = None,
    text: str | None = None,
    t: str | None = None,
    *,
    type: str | None = None,
    kind: str | None = None,
    target: str | None = None,
) -> Event:
    """Append one event to the open segment and reset ``sealed_at``.

    A sealed store starts a new segment; otherwise the last segment is used
    until it reaches 100 events.

    The M1 call form ``append_event(store, role, text, t)`` still works and
    writes a ``turn``. The typed form passes ``type`` (and ``kind``/
    ``target`` where the type allows them) as keywords.
    """
    if not store.is_dir() or not (store / EVIDENCE_DIR).is_dir():
        raise JianError(E_IO, f"存储目录未初始化：{store}")
    chain = _read_chain(store, required=True)
    if chain is None:
        raise JianError(E_IO, "缺少 chain.json")
    if "blobs" in chain:
        raise JianError(E_SCHEMA, "该 store 是 v2 格式，不能写入 v1 事件")
    sealed_at = chain["sealed_at"]
    rows = chain["segments"]
    last = rows[-1] if rows else None
    total = sum(int(row["count"]) for row in rows)
    if sealed_at is not None or last is None or int(last["count"]) >= SEGMENT_MAX_EVENTS:
        index = len(rows) + 1
        if index > 9999:
            raise JianError(E_SCHEMA, "段数量超出 seg-NNNN 范围")
        episode = f"seg-{index:04d}"
        new_segment = True
    else:
        episode = str(last["seg"])
        new_segment = False
    previous = str(last["last"]) if last else GENESIS_PREV
    stamp = t if t is not None else utc_now()
    if text is None:
        raise JianError(E_SCHEMA, "text 不能为空")
    event_type = type if type is not None else "turn"
    event = new_event(
        total + 1, episode, stamp, role, text, previous,
        type=event_type, kind=kind, target=target,
    )
    _append_bytes(store / EVIDENCE_DIR / f"{episode}.jsonl", event.to_line())
    if new_segment:
        rows.append({
            "seg": episode,
            "count": 1,
            "first": event.hash,
            "last": event.hash,
            "prev_seg": last["seg"] if last else None,
        })
    else:
        last["count"] = int(last["count"]) + 1
        last["last"] = event.hash
    _write_bytes(store / CHAIN_PATH, dumps({"v": 1, "sealed_at": None, "segments": rows}))
    _remove_if_exists(store / MANIFEST_PATH)
    return event


def append_payload_event(
    store: Path,
    modality: str,
    summary: str,
    payload: bytes,
    *,
    role: str | None = None,
    t: str | None = None,
    type: str = "turn",
    kind: str | None = None,
    target: str | None = None,
) -> Event:
    """Append one v2 envelope event; its bytes live in the blob store."""
    if not store.is_dir() or not (store / EVIDENCE_DIR).is_dir():
        raise JianError(E_IO, f"存储目录未初始化：{store}")
    chain = _read_chain(store, required=True)
    if chain is None:
        raise JianError(E_IO, "缺少 chain.json")
    rows = chain["segments"]
    if "blobs" in chain:
        blobs = list(chain["blobs"])
    elif rows:
        raise JianError(E_SCHEMA, "该 store 是 v1 格式，不能写入 v2 事件")
    else:
        blobs = []
    if not isinstance(payload, (bytes, bytearray)):
        raise JianError(E_SCHEMA, "payload 必须是 bytes")
    raw = bytes(payload)
    digest = _sha256(raw)
    sealed_at = chain["sealed_at"]
    last = rows[-1] if rows else None
    total = sum(int(row["count"]) for row in rows)
    if sealed_at is not None or last is None or int(last["count"]) >= SEGMENT_MAX_EVENTS:
        index = len(rows) + 1
        if index > 9999:
            raise JianError(E_SCHEMA, "段数量超出 seg-NNNN 范围")
        episode = f"seg-{index:04d}"
        new_segment = True
    else:
        episode = str(last["seg"])
        new_segment = False
    previous = str(last["last"]) if last else GENESIS_PREV
    stamp = t if t is not None else utc_now()
    event = new_event(
        total + 1, episode, stamp, role, None, previous,
        type=type, kind=kind, target=target,
        modality=modality, payload=f"sha256:{digest}", summary=summary,
    )
    put_blob(store, raw)
    _append_bytes(store / EVIDENCE_DIR / f"{episode}.jsonl", event.to_line())
    if new_segment:
        rows.append({
            "seg": episode,
            "count": 1,
            "first": event.hash,
            "last": event.hash,
            "prev_seg": last["seg"] if last else None,
        })
    else:
        last["count"] = int(last["count"]) + 1
        last["last"] = event.hash
    if digest not in blobs:
        blobs.append(digest)
    blobs.sort()
    _write_bytes(
        store / CHAIN_PATH,
        dumps({"v": 1, "sealed_at": None, "segments": rows, "blobs": blobs}),
    )
    _remove_if_exists(store / MANIFEST_PATH)
    return event


def event_full_text(store: Path, data: Mapping[str, object]) -> str:
    """Return the identity-layer text of one event, payload included.

    v1 returns ``text``. Envelope v2 returns the full bytes of the ``text``
    modality from ``blobs/`` and falls back to ``summary`` for every other
    modality, because only text carries identity-relevant content.
    """
    if data.get("v") != 2:
        value = data.get("text")
        return value if isinstance(value, str) else ""
    if data.get("modality") != "text":
        value = data.get("summary")
        return value if isinstance(value, str) else ""
    ref = data.get("payload")
    if not isinstance(ref, str) or not ref.startswith("sha256:"):
        raise JianError(E_SCHEMA, f"非法载荷引用：{ref}")
    try:
        return read_blob(store, ref[len("sha256:"):]).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise JianError(E_SCHEMA, "文本载荷不是 UTF-8 编码") from exc


def seal_store(store: Path) -> Verification:
    """Freeze the store by writing chain.json (with ``sealed_at``) and manifest.json."""
    evidence = _load_evidence(store)
    count, head, segments, events = _verify_evidence(evidence)
    blobs = _blob_digests(events)
    if blobs is not None:
        for digest in blobs:
            read_blob(store, digest)
    sealed_at = utc_now()
    _write_bytes(store / CHAIN_PATH, dumps(chain_document(sealed_at, segments, blobs)))
    manifest = _build_manifest(store, sealed_at, head, evidence, blobs)
    _write_bytes(store / MANIFEST_PATH, dumps(manifest))
    return Verification(count, len(segments), head, "sealed")


def export_capsule(store: Path, out: Path) -> Verification:
    """Pack a sealed store into a byte-reproducible ``.aiem`` file."""
    chain = _read_chain(store, required=False)
    if chain is None or chain["sealed_at"] is None:
        raise JianError(E_SCHEMA, "目录未封存，不能导出")
    evidence = _load_evidence(store)
    count, head, segments, events = _verify_evidence(evidence)
    blobs = _blob_digests(events)
    if not chain_matches(chain, chain["sealed_at"], segments, blobs):
        raise JianError(E_CHAIN_MISSING, "chain.json 与证据不符")
    chain_bytes = dumps(chain_document(str(chain["sealed_at"]), segments, blobs))
    revival = _render_revival(count, segments, head, str(chain["sealed_at"]), blobs)
    entries: dict[str, bytes] = {
        f"evidence/{name}.jsonl": data for name, data in evidence.items()
    }
    if blobs is not None:
        for digest in blobs:
            entries[f"blobs/{digest}"] = read_blob(store, digest)
    entries[CHAIN_PATH] = chain_bytes
    entries[REVIVAL_PATH] = revival.encode("utf-8")
    files = [
        {"path": name, "sha256": _sha256(data), "bytes": len(data)}
        for name, data in sorted(entries.items())
    ]
    manifest: dict[str, object] = {
        "capsule_version": 1,
        "schema": CAPSULE_SCHEMA,
        "created": str(chain["sealed_at"]),
        "hash_algo": "sha256",
        "head": head,
        "files": files,
        "signature": None,
    }
    if blobs is not None:
        manifest["format"] = 2
        manifest["blob_count"] = len(blobs)
    entries[MANIFEST_PATH] = dumps(manifest)
    _write_zip(entries, out)
    return Verification(count, len(segments), head, "sealed")


def import_capsule(src: Path, store: Path) -> Verification:
    """Verify a capsule and extract every entry byte-for-byte into a store."""
    result = _verify_capsule(src)
    entries = _read_zip(src)
    if store.exists():
        if not store.is_dir():
            raise JianError(E_IO, f"目标不是目录：{store}")
        if any(store.iterdir()):
            raise JianError(E_IO, f"目标目录非空：{store}")
    (store / EVIDENCE_DIR).mkdir(parents=True, exist_ok=True)
    for name, data in entries.items():
        if _entry_kind(name) is None:
            raise JianError(E_HEADER_MISMATCH, f"非法胶囊条目：{name}")
        _write_bytes(store / name, data)
    return result


def verify_path(path: Path) -> Verification:
    """Verify a store directory or a capsule file."""
    if path.is_dir():
        return _verify_store(path)
    if path.is_file():
        return _verify_capsule(path)
    raise JianError(E_IO, f"路径不存在：{path}")


def inspect_capsule(path: Path) -> CapsuleInfo:
    """Read capsule metadata without verifying evidence contents."""
    entries = _read_zip(path)
    manifest_blob = entries.get(MANIFEST_PATH)
    if manifest_blob is None:
        raise JianError(E_HEADER_MISMATCH, "胶囊缺少 manifest.json")
    manifest = _decode_manifest(manifest_blob)
    chain_blob = entries.get(CHAIN_PATH)
    if chain_blob is None:
        raise JianError(E_HEADER_MISMATCH, "胶囊缺少 chain.json")
    chain = _decode_chain(chain_blob)
    rows = chain["segments"]
    events = sum(int(row["count"]) for row in rows)
    files = manifest.get("files")
    files_count = len(files) if isinstance(files, list) else 0
    try:
        return CapsuleInfo(
            schema=str(manifest["schema"]),
            version=int(manifest["capsule_version"]),
            created=str(manifest["created"]),
            head=str(manifest["head"]),
            events=events,
            segments=len(rows),
            files=files_count,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise JianError(E_HEADER_MISMATCH, "manifest 字段不完整") from exc


def _verify_store(store: Path) -> Verification:
    evidence = _load_evidence(store)
    count, head, segments, events = _verify_evidence(evidence)
    blobs = _blob_digests(events)
    chain = _read_chain(store, required=False)
    state = "unsealed"
    if chain is not None:
        if not chain_matches(chain, chain["sealed_at"], segments, blobs):
            raise JianError(E_CHAIN_MISSING, "chain.json 与证据不符")
        if chain["sealed_at"] is not None:
            state = "sealed"
    if blobs is not None:
        for digest in blobs:
            read_blob(store, digest)
    if (store / MANIFEST_PATH).is_file():
        if chain is None:
            raise JianError(
                E_HEADER_MISMATCH, "manifest 存在但缺少 chain.json，请执行 seal 修复"
            )
        if chain["sealed_at"] is None:
            raise JianError(
                E_HEADER_MISMATCH, "manifest 与封存状态不符，请执行 seal 重新封存"
            )
        manifest = _decode_manifest(_read_bytes(store / MANIFEST_PATH))
        _check_manifest(
            manifest, _store_entries(store, evidence, blobs), head,
            str(chain["sealed_at"]),
        )
    return Verification(count, len(segments), head, state)


def _verify_capsule(path: Path) -> Verification:
    entries = _read_zip(path)
    if MANIFEST_PATH not in entries:
        raise JianError(E_HEADER_MISMATCH, "胶囊缺少 manifest.json")
    for name in entries:
        if _entry_kind(name) is None:
            raise JianError(E_HEADER_MISMATCH, f"非法胶囊条目：{name}")
    manifest = _decode_manifest(entries[MANIFEST_PATH])
    evidence: dict[str, bytes] = {}
    for name, data in entries.items():
        match = _EVIDENCE_RE.match(name)
        if match:
            evidence[match.group(1)] = data
    if not evidence:
        raise JianError(E_CHAIN_MISSING, "胶囊缺少证据段")
    count, head, segments, events = _verify_evidence(evidence)
    blobs = _blob_digests(events)
    chain_blob = entries.get(CHAIN_PATH)
    if chain_blob is None:
        raise JianError(E_HEADER_MISMATCH, "胶囊缺少 chain.json")
    chain = _decode_chain(chain_blob)
    sealed_at = chain["sealed_at"]
    if sealed_at is None:
        raise JianError(E_HEADER_MISMATCH, "胶囊 chain.json 未封存")
    if not chain_matches(chain, sealed_at, segments, blobs):
        raise JianError(E_CHAIN_MISSING, "chain.json 与证据不符")
    if blobs is not None:
        _check_capsule_blobs(entries, blobs)
    others = {name: data for name, data in entries.items() if name != MANIFEST_PATH}
    _check_manifest(manifest, others, head, str(sealed_at))
    return Verification(count, len(segments), head, "sealed")


def _check_manifest(manifest: Mapping[str, object], entries: Mapping[str, bytes],
                    head: str, sealed_at: str) -> None:
    keys = set(manifest)
    if keys == _MANIFEST_KEYS:
        capsule_format = 1
    elif keys == _MANIFEST_KEYS_V2:
        capsule_format = 2
    else:
        raise JianError(E_HEADER_MISMATCH, "manifest 字段缺失或多余")
    version = manifest["capsule_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise JianError(E_HEADER_MISMATCH, "capsule_version 必须为 1")
    if manifest["schema"] != CAPSULE_SCHEMA:
        raise JianError(E_HEADER_MISMATCH, "schema 不匹配")
    if manifest["hash_algo"] != "sha256":
        raise JianError(E_HEADER_MISMATCH, "hash_algo 必须是 sha256")
    if manifest["signature"] is not None:
        raise JianError(E_HEADER_MISMATCH, "signature 必须为 null")
    if manifest["created"] != sealed_at:
        raise JianError(E_HEADER_MISMATCH, "created 必须等于 chain.sealed_at")
    if manifest["head"] != head:
        raise JianError(E_HEADER_MISMATCH, "manifest.head 与末条事件不符")
    if capsule_format == 2:
        fmt = manifest["format"]
        if isinstance(fmt, bool) or not isinstance(fmt, int) or fmt != 2:
            raise JianError(E_HEADER_MISMATCH, "manifest.format 必须为 2")
        blob_count = manifest["blob_count"]
        if isinstance(blob_count, bool) or not isinstance(blob_count, int) \
                or blob_count < 0:
            raise JianError(E_HEADER_MISMATCH, "manifest.blob_count 非法")
    files = manifest["files"]
    if not isinstance(files, list):
        raise JianError(E_HEADER_MISMATCH, "manifest.files 必须是数组")
    listed: list[str] = []
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "bytes"}:
            raise JianError(E_HEADER_MISMATCH, "manifest.files 条目格式非法")
        path, digest, size = item["path"], item["sha256"], item["bytes"]
        if not isinstance(path, str) or not isinstance(digest, str):
            raise JianError(E_HEADER_MISMATCH, "manifest.files 条目类型非法")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise JianError(E_HEADER_MISMATCH, "manifest.files 的 bytes 非法")
        if path == MANIFEST_PATH or _entry_kind(path) is None:
            raise JianError(E_HEADER_MISMATCH, f"manifest.files 含非法路径：{path}")
        listed.append(path)
        if path not in entries:
            if _entry_kind(path) == "evidence":
                raise JianError(E_CHAIN_MISSING, f"缺少证据文件：{path}")
            raise JianError(E_HEADER_MISMATCH, f"manifest 列出的文件缺失：{path}")
        data = entries[path]
        if len(data) != size or _sha256(data) != digest:
            raise JianError(E_HEADER_MISMATCH, f"文件与 manifest 不符：{path}")
    if listed != sorted(listed):
        raise JianError(E_HEADER_MISMATCH, "manifest.files 未按 path 升序")
    if len(set(listed)) != len(listed):
        raise JianError(E_HEADER_MISMATCH, "manifest.files 含重复路径")
    extra = set(entries) - set(listed) - {MANIFEST_PATH}
    if extra:
        raise JianError(E_HEADER_MISMATCH, f"胶囊含未登记条目：{sorted(extra)[0]}")
    blob_paths = [path for path in listed if BLOB_RE.match(path)]
    if capsule_format == 2:
        if len(blob_paths) != manifest["blob_count"]:
            raise JianError(E_HEADER_MISMATCH, "blob_count 与 files 不符")
    elif blob_paths:
        raise JianError(E_HEADER_MISMATCH, "v1 manifest 不得包含载荷条目")


def _build_manifest(store: Path, created: str, head: str,
                    evidence: Mapping[str, bytes] | None = None,
                    blobs: Sequence[str] | None = None) -> dict[str, object]:
    entries = _store_entries(store, evidence, blobs)
    files = [
        {"path": name, "sha256": _sha256(data), "bytes": len(data)}
        for name, data in sorted(entries.items())
    ]
    manifest: dict[str, object] = {
        "capsule_version": 1,
        "schema": CAPSULE_SCHEMA,
        "created": created,
        "hash_algo": "sha256",
        "head": head,
        "files": files,
        "signature": None,
    }
    if blobs is not None:
        manifest["format"] = 2
        manifest["blob_count"] = len(blobs)
    return manifest


def _verify_evidence(
    evidence: Mapping[str, bytes],
) -> tuple[int, str, list[Segment], list[Event] | None]:
    try:
        count, head, segments = _scan_canonical(evidence)
        return count, head, segments, None
    except _FastPathMiss:
        parsed = _parse_segments(evidence)
        count, head = verify_evidence(parsed)
        segments = summarize(parsed)
        events = [event for _, rows in parsed for event in rows]
        return count, head, segments, events


def _store_entries(store: Path, evidence: Mapping[str, bytes] | None = None,
                   blobs: Sequence[str] | None = None) -> dict[str, bytes]:
    if evidence is None:
        evidence = _load_evidence(store)
    entries = {f"evidence/{name}.jsonl": data for name, data in evidence.items()}
    for name in (CHAIN_PATH, REVIVAL_PATH):
        path = store / name
        if path.is_file():
            entries[name] = _read_bytes(path)
    if blobs is not None:
        for digest in blobs:
            entries[f"{BLOBS_DIR}/{digest}"] = read_blob(store, digest)
    return entries


def _load_evidence(store: Path) -> dict[str, bytes]:
    evidence_dir = store / EVIDENCE_DIR
    if not evidence_dir.is_dir():
        raise JianError(E_CHAIN_MISSING, "缺少 evidence 目录")
    try:
        with os.scandir(evidence_dir) as scanned:
            names = sorted(
                entry.name for entry in scanned
                if entry.name.endswith(".jsonl") and entry.is_file()
            )
    except OSError as exc:
        raise JianError(E_IO, f"无法读取证据目录：{evidence_dir}") from exc
    if not names:
        raise JianError(E_CHAIN_MISSING, "证据目录为空")
    result: dict[str, bytes] = {}
    for filename in names:
        name = filename[: -len(".jsonl")]
        if not SEG_RE.match(name) or name in result:
            raise JianError(E_CHAIN_MISSING, f"非法证据文件名：{filename}")
        result[name] = _read_bytes(evidence_dir / filename)
    return result


def _parse_segments(evidence: Mapping[str, bytes]) -> list[tuple[str, list[Event]]]:
    parsed: list[tuple[str, list[Event]]] = []
    for name in sorted(evidence):
        try:
            text = evidence[name].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise JianError(E_SCHEMA, f"段 {name} 不是 UTF-8 编码") from exc
        if not text.endswith("\n"):
            raise JianError(E_SCHEMA, f"段 {name} 未以换行结尾")
        lines = text.split("\n")[:-1]
        events: list[Event] = []
        for line in lines:
            if not line:
                raise JianError(E_SCHEMA, f"段 {name} 含空行")
            event = parse_line(line)
            if line.encode("utf-8") != dumps(event.as_dict()):
                raise JianError(
                    E_NOT_CANONICAL, f"事件 {event.id} 不是规范字节", event.id
                )
            events.append(event)
        parsed.append((name, events))
    return parsed


def _read_chain(store: Path, *, required: bool) -> dict[str, object] | None:
    path = store / CHAIN_PATH
    if not path.is_file():
        if required:
            raise JianError(E_IO, f"缺少 chain.json：{store}")
        return None
    return _decode_chain(_read_bytes(path))


def _decode_chain(blob: bytes) -> dict[str, object]:
    try:
        data = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JianError(E_CHAIN_MISSING, "chain.json 解码失败") from exc
    try:
        return parse_chain(data)
    except JianError as exc:
        raise JianError(E_CHAIN_MISSING, exc.message) from exc


def _decode_manifest(blob: bytes) -> dict[str, object]:
    try:
        data = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JianError(E_HEADER_MISMATCH, "manifest.json 解码失败") from exc
    if not isinstance(data, dict):
        raise JianError(E_HEADER_MISMATCH, "manifest.json 必须是对象")
    return data


def _entry_kind(name: str) -> str | None:
    if name in (CHAIN_PATH, REVIVAL_PATH, MANIFEST_PATH):
        return "meta"
    if _EVIDENCE_RE.match(name):
        return "evidence"
    if BLOB_RE.match(name):
        return "blob"
    return None


def _write_zip(entries: Mapping[str, bytes], out: Path) -> None:
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
            for name in sorted(entries):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                info.external_attr = 0o644 << 16
                info.extra = b""
                archive.writestr(info, entries[name])
    except OSError as exc:
        raise JianError(E_IO, f"写入胶囊失败：{out}") from exc


def _read_zip(path: Path) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            entries: dict[str, bytes] = {}
            for info in archive.infolist():
                if info.is_dir():
                    raise JianError(E_HEADER_MISMATCH, "胶囊不应包含目录条目")
                if info.filename in entries:
                    raise JianError(E_HEADER_MISMATCH, "胶囊包含重复条目")
                entries[info.filename] = archive.read(info.filename)
            return entries
    except (OSError, zipfile.BadZipFile) as exc:
        raise JianError(E_IO, f"无法读取胶囊：{path}") from exc


def _append_bytes(path: Path, data: bytes) -> None:
    try:
        with path.open("ab") as handle:
            handle.write(data)
    except OSError as exc:
        raise JianError(E_IO, f"追加失败：{path}") from exc


def _remove_if_exists(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except OSError as exc:
        raise JianError(E_IO, f"删除失败：{path}") from exc
