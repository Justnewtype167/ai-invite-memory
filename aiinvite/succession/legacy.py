"""Legacy capsule export, verification and import (M15).

Three rules are enforced here and nowhere else:

1. ``succession.mode`` is ``inherit`` and nothing else (``E_SUCC_MODE``).
2. Removing evidence is only legal through ``redaction.json``.
3. ``successor_kid`` is recomputed from the shipped evidence and policy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from aiinvite.canonical import dumps
from aiinvite.capsule import verify_path
from aiinvite.chain import chain_matches, parse_chain
from aiinvite.errors import AiInviteError
from aiinvite.event import (
    GENESIS_PREV,
    ID_RE,
    SEGMENT_MAX_EVENTS,
    Event,
    format_id,
    new_event,
)
from aiinvite.kernel.kernel import Policy

from aiinvite.succession import archive
from aiinvite.succession.errors import (
    E_SUCC_DRIFT,
    E_SUCC_HEADER,
    E_SUCC_IO,
    E_SUCC_MODE,
    E_SUCC_REDACTION,
    E_SUCC_SCHEMA,
    SuccessionError,
)
from aiinvite.succession.model import (
    BLOBS_DIR,
    CHAIN_PATH,
    EVIDENCE_DIR,
    FORMAT_VERSION,
    HEX64_RE,
    LEGACY_FORMAT,
    LETTER_RE,
    MANIFEST_KEYS,
    MANIFEST_PATH,
    MODE_INHERIT,
    POLICY_PATH,
    REASONS,
    REDACTION_KEYS,
    REDACTION_PATH,
    REVIVAL_PATH,
    SUCCESSION_KEYS,
    SUCCESSION_PATH,
    LegacyInfo,
    Letter,
    canonical_files,
    digest,
    load_policy,
    policy_bytes,
    policy_from_bytes,
    recompute_kid,
)


def export_legacy(
    store: Path,
    out: Path,
    *,
    policy: Policy | None = None,
    letter: Letter | None = None,
    exclude: Mapping[str, str] | None = None,
) -> LegacyInfo:
    """Pack a sealed store into a legacy capsule.

    ``exclude`` maps an event id to one of ``third_party`` / ``private`` /
    ``requested``. Excluded events are removed from the evidence and every
    removal is written to ``redaction.json``; nothing disappears silently.
    """
    try:
        verify_path(store)
    except AiInviteError as error:
        raise SuccessionError(E_SUCC_SCHEMA, f"证据未通过校验：{error}") from error
    chain = archive.read_chain(store)
    sealed_at = chain["sealed_at"]
    if sealed_at is None:
        raise SuccessionError(E_SUCC_SCHEMA, "目录未封存，不能导出遗赠胶囊")
    events = archive.read_events(store)
    chosen = policy if policy is not None else Policy()
    origin_kid = recompute_kid(store, chosen)
    excluded = sorted(exclude or {})
    _check_exclusion(events, excluded, exclude or {})

    if excluded:
        evidence, _kept, segments = _redact(events, excluded)
        blobs = archive.blob_map(store, _kept)
        kid = archive.compile_evidence(evidence, blobs, chosen)
    else:
        evidence = archive.read_evidence_bytes(store)
        segments = archive.segments_from_chain(chain)
        blobs = archive.blob_map(store, events)
        kid = origin_kid

    blob_list = None if blobs is None else sorted(blobs)
    chain_data = archive.chain_bytes(str(sealed_at), segments, blob_list)
    head = segments[-1].last if segments else GENESIS_PREV
    policy_data = policy_bytes(chosen)
    redaction = {
        "excluded": excluded,
        "reason": {event_id: str(exclude[event_id]) for event_id in excluded},
        "redacted_kid": kid,
        "origin_kid": origin_kid,
        "evidence_sha256": archive.evidence_digest(evidence),
    }
    succession = {
        "successor_kid": kid,
        "derived_from": origin_kid,
        "redacted": bool(excluded),
        "created": str(sealed_at),
        "mode": MODE_INHERIT,
    }
    entries: dict[str, bytes] = {
        f"{EVIDENCE_DIR}/{name}.jsonl": data for name, data in evidence.items()
    }
    entries[CHAIN_PATH] = chain_data
    entries[REVIVAL_PATH] = archive.revival_text(
        len(evidence), head, str(sealed_at)
    ).encode("utf-8")
    entries[POLICY_PATH] = policy_data
    entries[REDACTION_PATH] = dumps(redaction)
    entries[SUCCESSION_PATH] = dumps(succession)
    if blobs is not None:
        for item, data in blobs.items():
            entries[f"{BLOBS_DIR}/{item}"] = data
    if letter is not None:
        entries["letters/letter-1.txt"] = letter.to_text().encode("utf-8")
    manifest = archive.manifest_document(
        str(sealed_at), kid, policy_data, head, canonical_files(entries)
    )
    entries[MANIFEST_PATH] = dumps(manifest)
    archive.write_zip(entries, out)
    return LegacyInfo(
        kid, origin_kid, kid, archive.count_events(evidence), len(segments),
        bool(excluded), tuple(excluded),
    )


def verify_legacy(path: Path) -> LegacyInfo:
    """Verify a legacy capsule completely, including the recomputed identity."""
    entries = archive.read_zip(path)
    manifest = archive.decode_json(
        archive.require(entries, MANIFEST_PATH), MANIFEST_PATH, E_SUCC_HEADER
    )
    _check_manifest_shape(manifest)
    succession = archive.decode_json(
        archive.require(entries, SUCCESSION_PATH), SUCCESSION_PATH, E_SUCC_SCHEMA
    )
    if succession.get("mode") != MODE_INHERIT:
        raise SuccessionError(
            E_SUCC_MODE,
            f"mode 只能是 {MODE_INHERIT}，收到：{succession.get('mode')}",
        )
    redaction = archive.decode_json(
        archive.require(entries, REDACTION_PATH), REDACTION_PATH, E_SUCC_REDACTION
    )
    _check_succession_shape(succession)
    _check_redaction_shape(redaction)
    _check_files(manifest, entries)

    policy_data = archive.require(entries, POLICY_PATH)
    if manifest["policy_digest"] != digest(policy_data):
        raise SuccessionError(E_SUCC_HEADER, "policy_digest 与 policy.json 不符")
    policy = policy_from_bytes(policy_data)

    evidence = archive.evidence_entries(entries)
    count, head, segments, parsed = archive.verify_evidence_set(evidence)
    blobs = archive.blob_map_from_entries(entries, parsed)
    blob_list = None if blobs is None else sorted(blobs)
    chain = archive.decode_json(
        archive.require(entries, CHAIN_PATH), CHAIN_PATH, E_SUCC_HEADER
    )
    try:
        decoded = parse_chain(chain)
    except AiInviteError as error:
        raise SuccessionError(E_SUCC_HEADER, f"chain.json 非法：{error}") from error
    sealed_at = decoded["sealed_at"]
    if sealed_at is None:
        raise SuccessionError(E_SUCC_HEADER, "legacy chain.json 未封存")
    if not chain_matches(decoded, sealed_at, segments, blob_list):
        raise SuccessionError(E_SUCC_HEADER, "chain.json 与证据不符")
    if manifest["head"] != head:
        raise SuccessionError(E_SUCC_HEADER, "manifest.head 与末条事件不符")
    if manifest["created"] != sealed_at:
        raise SuccessionError(E_SUCC_HEADER, "manifest.created 必须等于 chain.sealed_at")

    excluded = tuple(redaction["excluded"])
    if archive.evidence_digest(evidence) != redaction["evidence_sha256"]:
        raise SuccessionError(E_SUCC_REDACTION, "redaction.json 与证据哈希不绑定")
    _check_redaction_values(redaction, manifest["kid"], excluded)
    _check_succession_values(succession, redaction, excluded)
    for name, data in entries.items():
        if LETTER_RE.match(name):
            Letter.from_text(data.decode("utf-8", "replace"))
    kid = archive.compile_evidence(evidence, blobs, policy)
    if kid != manifest["kid"]:
        raise SuccessionError(
            E_SUCC_DRIFT, f"重算 kid 与 manifest 不符：{kid} != {manifest['kid']}"
        )
    return LegacyInfo(
        manifest["kid"], redaction["origin_kid"], succession["successor_kid"],
        count, len(segments), bool(excluded), excluded,
    )


def import_legacy(src: Path, store: Path) -> LegacyInfo:
    """Verify a legacy capsule and extract its evidence and declarations."""
    info = verify_legacy(src)
    entries = archive.read_zip(src)
    if store.exists():
        if not store.is_dir():
            raise SuccessionError(E_SUCC_IO, f"目标不是目录：{store}")
        if any(store.iterdir()):
            raise SuccessionError(E_SUCC_IO, f"目标目录非空：{store}")
    for name, data in entries.items():
        if name == MANIFEST_PATH:
            continue
        if archive.entry_kind(name) is None:
            raise SuccessionError(E_SUCC_HEADER, f"非法胶囊条目：{name}")
        archive.write_bytes(store / name, data)
    policy = load_policy(store / POLICY_PATH)
    kid = recompute_kid(store, policy)
    if kid != info.successor_kid:
        raise SuccessionError(
            E_SUCC_DRIFT,
            f"导入后重算 kid 与 successor_kid 不符：{kid} != {info.successor_kid}",
        )
    return info


def _check_exclusion(
    events: Sequence[Event], excluded: Sequence[str], reasons: Mapping[str, str]
) -> None:
    known = {event.id for event in events}
    if len(excluded) == len(events):
        raise SuccessionError(E_SUCC_REDACTION, "不能排除全部证据")
    for event_id in excluded:
        if not ID_RE.match(event_id) or event_id not in known:
            raise SuccessionError(
                E_SUCC_REDACTION, f"被排除的事件不存在：{event_id}"
            )
        if reasons.get(event_id) not in REASONS:
            raise SuccessionError(
                E_SUCC_REDACTION,
                f"事件 {event_id} 的排除原因非法：{reasons.get(event_id)}",
            )


def _redact(
    events: Sequence[Event], excluded: Sequence[str]
) -> tuple[dict[str, bytes], list[Event], list[archive.Segment]]:
    """Rebuild a valid chain without the excluded events.

    Removing an event shifts every later index, so ids, segment names and the
    ``prev`` links are recomputed. A ``feedback`` target is remapped; if its
    target was excluded the export fails instead of silently retargeting.
    """
    removed = set(excluded)
    kept = [event for event in events if event.id not in removed]
    id_map = {event.id: format_id(index + 1) for index, event in enumerate(kept)}
    rebuilt: list[Event] = []
    groups: dict[str, list[Event]] = {}
    previous = GENESIS_PREV
    for index, event in enumerate(kept):
        seq = index + 1
        episode = f"seg-{(seq - 1) // SEGMENT_MAX_EVENTS + 1:04d}"
        target = event.target
        if event.type == "feedback" and target is not None:
            if target not in id_map:
                raise SuccessionError(
                    E_SUCC_REDACTION, f"feedback 的 target {target} 也被排除，无法映射"
                )
            target = id_map[target]
        fresh = _rebuild_event(event, seq, episode, previous, target)
        previous = fresh.hash
        rebuilt.append(fresh)
        groups.setdefault(episode, []).append(fresh)
    evidence = {
        name: b"".join(event.to_line() for event in rows)
        for name, rows in groups.items()
    }
    return evidence, rebuilt, archive.segments_from_groups(groups)


def _rebuild_event(
    event: Event, seq: int, episode: str, previous: str, target: str | None
) -> Event:
    extras: dict[str, object] = {
        "type": event.type, "kind": event.kind, "target": target,
    }
    if event.type == "refusal":
        extras["trace"] = event.trace
    if event.type == "proposal":
        extras.update({
            "model": event.model, "prompt_sha": event.prompt_sha,
            "quant": event.quant, "weights_sha": event.weights_sha,
            "temp_milli": event.temp_milli, "seed": event.seed,
        })
    if event.v == 2:
        return new_event(
            seq, episode, event.t, event.role, None, previous,
            modality=event.modality, payload=event.payload,
            summary=event.summary, **extras,
        )
    return new_event(seq, episode, event.t, event.role, event.text, previous, **extras)


def _check_manifest_shape(manifest: Mapping[str, object]) -> None:
    if set(manifest) != MANIFEST_KEYS:
        raise SuccessionError(E_SUCC_HEADER, "manifest 字段缺失或多余")
    if manifest["format"] != LEGACY_FORMAT:
        raise SuccessionError(E_SUCC_HEADER, f"format 必须是 {LEGACY_FORMAT}")
    version = manifest["format_version"]
    if isinstance(version, bool) or not isinstance(version, int) \
            or version != FORMAT_VERSION:
        raise SuccessionError(E_SUCC_HEADER, "format_version 必须为 1")
    for name in ("created", "kid", "policy_digest", "head"):
        if not isinstance(manifest[name], str):
            raise SuccessionError(E_SUCC_HEADER, f"manifest.{name} 必须是字符串")
    for name in ("kid", "policy_digest", "head"):
        if not HEX64_RE.match(str(manifest[name])):
            raise SuccessionError(E_SUCC_HEADER, f"manifest.{name} 非法")
    if manifest["signature"] is not None:
        raise SuccessionError(E_SUCC_HEADER, "signature 必须为 null")
    if not isinstance(manifest["files"], list):
        raise SuccessionError(E_SUCC_HEADER, "manifest.files 必须是数组")


def _check_files(manifest: Mapping[str, object], entries: Mapping[str, bytes]) -> None:
    listed: list[str] = []
    for item in manifest["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "bytes"}:
            raise SuccessionError(E_SUCC_HEADER, "manifest.files 条目格式非法")
        path, expected, size = item["path"], item["sha256"], item["bytes"]
        if not isinstance(path, str) or not isinstance(expected, str):
            raise SuccessionError(E_SUCC_HEADER, "manifest.files 条目类型非法")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise SuccessionError(E_SUCC_HEADER, "manifest.files 的 bytes 非法")
        if path == MANIFEST_PATH or archive.entry_kind(path) is None:
            raise SuccessionError(E_SUCC_HEADER, f"manifest.files 含非法路径：{path}")
        listed.append(path)
        data = entries.get(path)
        if data is None:
            raise SuccessionError(E_SUCC_HEADER, f"manifest 列出的文件缺失：{path}")
        if len(data) != size:
            raise SuccessionError(_tamper_code(path), f"文件大小与 manifest 不符：{path}")
        if digest(data) != expected:
            raise SuccessionError(_tamper_code(path), f"文件与 manifest 不符：{path}")
    if listed != sorted(listed):
        raise SuccessionError(E_SUCC_HEADER, "manifest.files 未按 path 升序")
    if len(set(listed)) != len(listed):
        raise SuccessionError(E_SUCC_HEADER, "manifest.files 含重复路径")
    extra = set(entries) - set(listed) - {MANIFEST_PATH}
    if extra:
        raise SuccessionError(E_SUCC_HEADER, f"胶囊含未登记条目：{sorted(extra)[0]}")


def _tamper_code(path: str) -> str:
    if path == REDACTION_PATH:
        return E_SUCC_REDACTION
    if path == SUCCESSION_PATH:
        return E_SUCC_SCHEMA
    return E_SUCC_HEADER


def _check_redaction_shape(redaction: Mapping[str, object]) -> None:
    if set(redaction) != REDACTION_KEYS:
        raise SuccessionError(E_SUCC_REDACTION, "redaction.json 字段缺失或多余")
    if not isinstance(redaction["excluded"], list):
        raise SuccessionError(E_SUCC_REDACTION, "excluded 必须是数组")
    if not isinstance(redaction["reason"], dict):
        raise SuccessionError(E_SUCC_REDACTION, "reason 必须是对象")
    for name in ("redacted_kid", "origin_kid", "evidence_sha256"):
        value = redaction[name]
        if not isinstance(value, str) or not HEX64_RE.match(value):
            raise SuccessionError(E_SUCC_REDACTION, f"{name} 必须是 64 位十六进制")


def _check_redaction_values(
    redaction: Mapping[str, object], kid: str, excluded: Sequence[str]
) -> None:
    if list(excluded) != sorted(excluded) or len(set(excluded)) != len(excluded):
        raise SuccessionError(E_SUCC_REDACTION, "excluded 未严格升序或含重复")
    for event_id in excluded:
        if not isinstance(event_id, str) or not ID_RE.match(event_id):
            raise SuccessionError(E_SUCC_REDACTION, f"excluded 含非法事件 id：{event_id}")
        if redaction["reason"].get(event_id) not in REASONS:
            raise SuccessionError(
                E_SUCC_REDACTION, f"excluded 的 {event_id} 缺少合法原因"
            )
    if set(redaction["reason"]) != set(excluded):
        raise SuccessionError(E_SUCC_REDACTION, "reason 与 excluded 不一致")
    if redaction["redacted_kid"] != kid:
        raise SuccessionError(E_SUCC_REDACTION, "redacted_kid 与 manifest.kid 不符")
    if excluded:
        if redaction["origin_kid"] == kid:
            raise SuccessionError(
                E_SUCC_REDACTION, "发生过脱敏，origin_kid 不得等于 redacted_kid"
            )
    elif redaction["origin_kid"] != kid:
        raise SuccessionError(
            E_SUCC_REDACTION, "未脱敏时 origin_kid 必须等于 manifest.kid"
        )


def _check_succession_shape(succession: Mapping[str, object]) -> None:
    if set(succession) != SUCCESSION_KEYS:
        raise SuccessionError(E_SUCC_SCHEMA, "succession.json 字段缺失或多余")
    for name in ("successor_kid", "derived_from"):
        value = succession[name]
        if not isinstance(value, str) or not HEX64_RE.match(value):
            raise SuccessionError(E_SUCC_SCHEMA, f"{name} 必须是 64 位十六进制")
    if not isinstance(succession["redacted"], bool):
        raise SuccessionError(E_SUCC_SCHEMA, "redacted 必须是布尔值")
    if not isinstance(succession["created"], str) or not succession["created"]:
        raise SuccessionError(E_SUCC_SCHEMA, "created 必须是非空字符串")


def _check_succession_values(
    succession: Mapping[str, object], redaction: Mapping[str, object],
    excluded: Sequence[str],
) -> None:
    if succession["successor_kid"] != redaction["redacted_kid"]:
        raise SuccessionError(E_SUCC_DRIFT, "successor_kid 与 redacted_kid 不符")
    if succession["derived_from"] != redaction["origin_kid"]:
        raise SuccessionError(E_SUCC_DRIFT, "derived_from 与 origin_kid 不符")
    if succession["redacted"] != bool(excluded):
        raise SuccessionError(E_SUCC_SCHEMA, "redacted 标记与 excluded 不一致")
