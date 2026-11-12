"""Rebuildable FTS5 index over M1 evidence (M3).

The index lives under ``store/.index/`` and can always be reconstructed from
``store/evidence/seg-*.jsonl``. Derived static fields are cached in explicit
tables; nothing that depends on ``now`` is cached.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from aiinvite.event import event_text
from aiinvite.recall.errors import E_RC_IO, E_RC_NO_INDEX, E_RC_STALE, RecallError
from aiinvite.recall.tokenizer import bigrams, estimate_tokens, index_terms

INDEX_DIR = ".index"
INDEX_FILE = "idx.sqlite"
INDEX_VERSION = "2"
EVIDENCE_DIR = "evidence"
PROMISE_WORDS = ("答应", "保证", "说好", "下次一定")
PROMISE_DONE = ("已", "完成了")
SAMPLE_LIMIT = 1000

_SCHEMA = (
    # FTS5 reserves the shadow table name ``<table>_data``, so the virtual
    # table is ``fts_ev`` and the explicit derived cache can own ``ev_data``.
    "CREATE VIRTUAL TABLE fts_ev USING fts5("
    "event_id UNINDEXED, seg UNINDEXED, ts UNINDEXED, bg)",
    "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE ev_data(event_id TEXT PRIMARY KEY, text TEXT, "
    "tokens INTEGER, is_promise INTEGER)",
    "CREATE TABLE ev_time(event_id TEXT PRIMARY KEY, seg TEXT, ts TEXT, "
    "md TEXT, year INTEGER)",
    "CREATE INDEX ev_time_md ON ev_time(md)",
    "CREATE INDEX ev_data_promise ON ev_data(is_promise)",
)


@dataclass(frozen=True)
class IndexStatus:
    """State of the derived index relative to the evidence tail."""

    events_indexed: int
    lsn: str
    stale: bool
    verified: int = 0


@dataclass(frozen=True)
class StoredEvent:
    """One evidence event as read back from disk."""

    event_id: str
    seg: str
    ts: str
    text: str


def evidence_files(store: Path) -> list[Path]:
    """Return the evidence segments sorted by segment name."""
    folder = store / EVIDENCE_DIR
    if not folder.is_dir():
        raise RecallError(E_RC_IO, f"缺少证据目录：{folder}")
    try:
        files = sorted(folder.glob("seg-*.jsonl"))
    except OSError as exc:
        raise RecallError(E_RC_IO, f"无法读取证据目录：{folder}") from exc
    if not files:
        raise RecallError(E_RC_IO, f"证据目录为空：{folder}")
    return files


def evidence_tail(store: Path) -> str:
    """Return the event id of the last evidence line."""
    for path in reversed(evidence_files(store)):
        lines = _read_lines(path)
        if lines:
            try:
                data = json.loads(lines[-1])
            except json.JSONDecodeError as exc:
                raise RecallError(E_RC_IO, f"证据行无法解析：{path}") from exc
            event_id = data.get("id")
            if not isinstance(event_id, str):
                raise RecallError(E_RC_IO, f"证据行缺少 id：{path}")
            return event_id
    raise RecallError(E_RC_IO, "证据目录为空")


def read_tail_events(
    store: Path, limit: int = 8, last_segment: str | None = None
) -> list[StoredEvent]:
    """Return the last ``limit`` evidence events in chronological order.

    When ``last_segment`` (from index meta) is given, only the needed segment
    files are read instead of listing the whole evidence directory.
    """
    if limit <= 0:
        return []
    folder = store / EVIDENCE_DIR
    if not folder.is_dir():
        raise RecallError(E_RC_IO, f"缺少证据目录：{folder}")
    if last_segment is None:
        paths = list(reversed(evidence_files(store)))
    else:
        try:
            number = int(last_segment.split("-")[1])
        except (IndexError, ValueError) as exc:
            raise RecallError(E_RC_IO, f"非法段名：{last_segment}") from exc
        paths = [folder / f"seg-{index:04d}.jsonl" for index in range(number, 0, -1)]
    collected: list[StoredEvent] = []
    for path in paths:
        if not path.is_file():
            raise RecallError(E_RC_IO, f"缺少证据段：{path}")
        lines = _read_lines(path)
        needed = limit - len(collected)
        if len(lines) > needed:
            lines = lines[-needed:]
        collected = [_parse_stored(line, path) for line in lines] + collected
        if len(collected) >= limit:
            break
    return collected[-limit:]


def is_promise(text: str) -> bool:
    """Return whether ``text`` looks like an unfinished promise."""
    if not any(word in text for word in PROMISE_WORDS):
        return False
    return not any(word in text for word in PROMISE_DONE)


def build_index(store: Path) -> IndexStatus:
    """Rebuild ``store/.index/`` from evidence from scratch."""
    index_dir = store / INDEX_DIR
    try:
        if index_dir.exists():
            shutil.rmtree(index_dir)
        index_dir.mkdir(parents=True)
    except OSError as exc:
        raise RecallError(E_RC_IO, f"无法重建索引目录：{index_dir}") from exc
    connection = _connect(index_dir / INDEX_FILE, readonly=False)
    count = 0
    head = ""
    try:
        for statement in _SCHEMA:
            connection.execute(statement)
        for path in evidence_files(store):
            rows_ev: list[tuple[str, str, str, str]] = []
            rows_data: list[tuple[str, str, int, int]] = []
            rows_time: list[tuple[str, str, str, str, int]] = []
            for event in _iter_stored(path):
                ev_row, data_row, time_row = _index_rows(event)
                rows_ev.append(ev_row)
                rows_data.append(data_row)
                rows_time.append(time_row)
                count += 1
                head = event.event_id
            _insert_rows(connection, rows_ev, rows_data, rows_time)
        if count == 0:
            raise RecallError(E_RC_IO, "证据目录为空")
        last_path = evidence_files(store)[-1]
        connection.executemany(
            "INSERT INTO meta(key, value) VALUES(?, ?)",
            [
                ("head", head),
                ("count", str(count)),
                ("version", INDEX_VERSION),
                ("last_seg", last_path.stem),
                ("last_size", str(last_path.stat().st_size)),
                ("build_id", uuid.uuid4().hex),
            ],
        )
        connection.commit()
    except sqlite3.DatabaseError as exc:
        raise RecallError(E_RC_IO, f"建索引失败：{exc}") from exc
    finally:
        connection.close()
    return IndexStatus(count, head, False, 0)


def update_index(store: Path) -> IndexStatus:
    """Index every evidence event after ``meta.head``, reading only new bytes.

    Evidence is append-only, so the indexed size of the last segment is also
    the byte offset where the next update starts: a turn that appends one
    event reads one event, not the whole store. A changed boundary (truncated
    segment, rewritten tail, missing segment) raises ``E_RC_STALE`` so the
    caller rebuilds instead of indexing history the index never saw.
    """
    current = index_status(store)
    if not current.stale:
        return IndexStatus(current.events_indexed, current.lsn, False, 0)
    meta = load_meta(store)
    last_seg = meta.get("last_seg")
    last_size = meta.get("last_size")
    if not last_seg or last_size is None:
        raise RecallError(E_RC_STALE, "索引缺少段偏移，无法增量更新")
    offset = int(last_size)
    paths = evidence_files(store)
    names = [path.stem for path in paths]
    if last_seg not in names:
        raise RecallError(E_RC_STALE, f"索引指向的段已不存在：{last_seg}")
    start = names.index(last_seg)
    boundary = paths[start]
    try:
        size = boundary.stat().st_size
    except OSError as exc:
        raise RecallError(E_RC_IO, f"无法读取证据段：{boundary}") from exc
    if size < offset:
        raise RecallError(E_RC_STALE, f"证据段被截断：{boundary.name}")
    if offset and _last_event_id(boundary, offset) != meta.get("head"):
        raise RecallError(E_RC_STALE, f"索引 head 与证据末尾不一致：{boundary.name}")

    rows_ev: list[tuple[str, str, str, str]] = []
    rows_data: list[tuple[str, str, int, int]] = []
    rows_time: list[tuple[str, str, str, str, int]] = []
    head = str(meta.get("head", ""))
    count = int(meta["count"])
    end_seg = last_seg
    end_offset = offset
    for number in range(start, len(paths)):
        path = paths[number]
        begin = offset if number == start else 0
        events, complete = _read_appended(path, begin)
        if number == start:
            end_offset = complete
        for event in events:
            ev_row, data_row, time_row = _index_rows(event)
            rows_ev.append(ev_row)
            rows_data.append(data_row)
            rows_time.append(time_row)
            head = event.event_id
            count += 1
        if number == len(paths) - 1:
            end_seg = path.stem
            end_offset = complete
    if not rows_ev and end_seg == last_seg and end_offset == offset:
        # Only an unfinished trailing line arrived; the index is still behind.
        return IndexStatus(count, head, True, 0)
    connection = _connect(store / INDEX_DIR / INDEX_FILE, readonly=False)
    try:
        if rows_ev:
            _insert_rows(connection, rows_ev, rows_data, rows_time)
        connection.executemany(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            [
                ("head", head),
                ("count", str(count)),
                ("last_seg", end_seg),
                ("last_size", str(end_offset)),
            ],
        )
        connection.commit()
    except sqlite3.DatabaseError as exc:
        raise RecallError(E_RC_IO, f"增量索引失败：{exc}") from exc
    finally:
        connection.close()
    return IndexStatus(count, head, False, 0)


def index_status(store: Path, verify_sample: int = 0) -> IndexStatus:
    """Report index state and optionally reconcile sampled cached texts.

    Staleness is checked against the last evidence segment's size and the
    presence of a newer segment, which is equivalent to comparing
    ``meta.head`` with the evidence tail but avoids listing 2000 files on
    every query. With ``verify_sample > 0`` the cached text of up to that
    many events is compared byte-for-byte with the evidence; any mismatch
    raises ``E_RC_STALE``.
    """
    meta = load_meta(store)
    if "head" not in meta or "count" not in meta:
        raise RecallError(E_RC_NO_INDEX, "索引元数据缺失，请先 build")
    stale = _stale_fast(store, meta)
    verified = 0
    if verify_sample > 0:
        verified = _verify_sample(store, min(verify_sample, SAMPLE_LIMIT))
    return IndexStatus(int(meta["count"]), meta["head"], stale, verified)


def load_meta(store: Path) -> dict[str, str]:
    """Read the derived index metadata table as a string map."""
    database = store / INDEX_DIR / INDEX_FILE
    if not database.is_file():
        raise RecallError(E_RC_NO_INDEX, f"索引不存在，请先 build：{database}")
    connection = _connect(database, readonly=True)
    try:
        rows = connection.execute("SELECT key, value FROM meta").fetchall()
    except sqlite3.DatabaseError as exc:
        raise RecallError(E_RC_IO, f"索引元数据损坏：{exc}") from exc
    finally:
        connection.close()
    if not rows:
        raise RecallError(E_RC_NO_INDEX, "索引元数据缺失，请先 build")
    return {str(row["key"]): str(row["value"]) for row in rows}


def _stale_fast(store: Path, meta: dict[str, str]) -> bool:
    folder = store / EVIDENCE_DIR
    if not folder.is_dir():
        raise RecallError(E_RC_IO, f"缺少证据目录：{folder}")
    last_segment = meta.get("last_seg")
    last_size = meta.get("last_size")
    if last_segment is None or last_size is None:
        return evidence_tail(store) != meta.get("head")
    path = folder / f"{last_segment}.jsonl"
    try:
        size = path.stat().st_size
    except OSError:
        return True
    if size != int(last_size):
        return True
    try:
        number = int(last_segment.split("-")[1])
    except IndexError:
        return True
    return (folder / f"seg-{number + 1:04d}.jsonl").exists()


def _verify_sample(store: Path, sample: int) -> int:
    database = store / INDEX_DIR / INDEX_FILE
    connection = _connect(database, readonly=True)
    try:
        total = int(
            connection.execute("SELECT COUNT(*) FROM ev_data").fetchone()[0]
        )
        if total <= 0:
            raise RecallError(E_RC_STALE, "索引没有缓存文本，无法对账")
        if sample > total:
            sample = total
        wanted = sorted({1 + index * (total - 1) // sample for index in range(sample)})
        wanted_ids = [f"ev_{sequence:06d}" for sequence in wanted]
        cached: dict[str, str] = {}
        for offset in range(0, len(wanted_ids), 200):
            chunk = wanted_ids[offset:offset + 200]
            marks = ",".join("?" for _ in chunk)
            for row in connection.execute(
                f"SELECT event_id, text FROM ev_data WHERE event_id IN ({marks})",
                chunk,
            ):
                cached[str(row["event_id"])] = str(row["text"])
    except sqlite3.DatabaseError as exc:
        raise RecallError(E_RC_IO, f"对账读取失败：{exc}") from exc
    finally:
        connection.close()
    found: dict[str, str] = {}
    wanted_set = set(wanted_ids)
    for path in evidence_files(store):
        for event in _iter_stored(path):
            if event.event_id in wanted_set:
                found[event.event_id] = event.text
    for event_id in wanted_ids:
        if event_id not in found:
            raise RecallError(
                E_RC_STALE, f"证据中找不到缓存条目：{event_id}"
            )
        if event_id not in cached:
            raise RecallError(E_RC_STALE, f"索引缺少缓存文本：{event_id}")
        if cached[event_id] != found[event_id]:
            raise RecallError(
                E_RC_STALE, f"缓存文本与证据不一致：{event_id}"
            )
    return len(wanted_ids)


def connect_index(store: Path, readonly: bool = True) -> sqlite3.Connection:
    """Open the derived index; raise ``E_RC_NO_INDEX`` when it is absent."""
    database = store / INDEX_DIR / INDEX_FILE
    if not database.is_file():
        raise RecallError(E_RC_NO_INDEX, f"索引不存在，请先 build：{database}")
    return _connect(database, readonly=readonly)


def parse_stamp(value: str) -> datetime:
    """Parse a canonical ``...Z`` evidence timestamp into UTC."""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise RecallError(E_RC_IO, f"非法时间戳：{value}") from exc
    return parsed.replace(tzinfo=timezone.utc)


def parse_now(value: str | None) -> datetime:
    """Parse a timezone-aware ISO 8601 ``now`` value into UTC."""
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RecallError(E_RC_IO, f"now 不是合法的时间：{value}") from exc
    if parsed.tzinfo is None:
        raise RecallError(E_RC_IO, "now 必须带时区")
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _connect(database: Path, readonly: bool) -> sqlite3.Connection:
    try:
        if readonly:
            uri = "file:///" + database.resolve().as_posix() + "?mode=ro"
            connection = sqlite3.connect(uri, uri=True)
        else:
            connection = sqlite3.connect(str(database))
    except sqlite3.Error as exc:
        raise RecallError(E_RC_IO, f"无法打开索引：{database}") from exc
    connection.row_factory = sqlite3.Row
    return connection


def _read_lines(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RecallError(E_RC_IO, f"读取证据失败：{path}") from exc
    except UnicodeDecodeError as exc:
        raise RecallError(E_RC_IO, f"证据不是 UTF-8：{path}") from exc
    return [line for line in text.split("\n") if line]


def _iter_stored(path: Path) -> Iterator[StoredEvent]:
    for line in _read_lines(path):
        yield _parse_stored(line, path)


def _parse_stored(line: str, path: Path) -> StoredEvent:
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        raise RecallError(E_RC_IO, f"证据行无法解析：{path}") from exc
    event_id = data.get("id")
    stamp = data.get("t")
    text = event_text(data)
    if not isinstance(event_id, str) or not isinstance(stamp, str) \
            or not isinstance(text, str):
        raise RecallError(E_RC_IO, f"证据字段缺失：{path}")
    return StoredEvent(event_id, str(data.get("ep", path.stem)), stamp, text)


def _sequence(event_id: str) -> int:
    try:
        return int(event_id[3:])
    except ValueError as exc:
        raise RecallError(E_RC_IO, f"非法事件 id：{event_id}") from exc

def _index_rows(event: StoredEvent) -> tuple[
    tuple[str, str, str, str],
    tuple[str, str, int, int],
    tuple[str, str, str, str, int],
]:
    """Build the three index rows for one event, shared by build and update."""
    ev_row = (event.event_id, event.seg, event.ts, index_terms(event.text))
    data_row = (
        event.event_id,
        event.text,
        estimate_tokens(event.text),
        1 if is_promise(event.text) else 0,
    )
    time_row = (
        event.event_id,
        event.seg,
        event.ts,
        event.ts[5:10],
        int(event.ts[:4]),
    )
    return ev_row, data_row, time_row


def _insert_rows(
    connection: sqlite3.Connection,
    rows_ev: list[tuple[str, str, str, str]],
    rows_data: list[tuple[str, str, int, int]],
    rows_time: list[tuple[str, str, str, str, int]],
) -> None:
    connection.executemany(
        "INSERT INTO fts_ev(event_id, seg, ts, bg) VALUES(?, ?, ?, ?)",
        rows_ev,
    )
    connection.executemany(
        "INSERT INTO ev_data(event_id, text, tokens, is_promise) "
        "VALUES(?, ?, ?, ?)",
        rows_data,
    )
    connection.executemany(
        "INSERT INTO ev_time(event_id, seg, ts, md, year) VALUES(?, ?, ?, ?, ?)",
        rows_time,
    )


def _read_appended(path: Path, offset: int) -> tuple[list[StoredEvent], int]:
    """Parse complete lines at offset; ignore a trailing partial line."""
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read()
    except OSError as exc:
        raise RecallError(E_RC_IO, f"无法读取证据段：{path}") from exc
    cut = data.rfind(b"\n")
    if cut < 0:
        return [], offset
    body = data[: cut + 1]
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RecallError(E_RC_IO, f"证据不是 UTF-8：{path}") from exc
    events = [_parse_stored(line, path) for line in text.split("\n") if line]
    return events, offset + len(body)


def _last_event_id(path: Path, offset: int) -> str | None:
    """Return the id of the complete line that ends at offset."""
    window = 4096
    while True:
        start = max(0, offset - window)
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                chunk = handle.read(offset - start)
        except OSError as exc:
            raise RecallError(E_RC_IO, f"无法读取证据段：{path}") from exc
        if not chunk.endswith(b"\n"):
            return None
        body = chunk[:-1]
        cut = body.rfind(b"\n")
        if cut < 0:
            if start > 0:
                window *= 4
                continue
            line = body
        else:
            line = body[cut + 1:]
        try:
            data = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        event_id = data.get("id")
        return event_id if isinstance(event_id, str) else None
