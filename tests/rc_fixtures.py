"""Shared fixtures for the M3 recall tests (not a test module)."""

from __future__ import annotations

import atexit
import json
import random
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jian.event import GENESIS_PREV, new_event

ROOT = Path(__file__).resolve().parents[1]
LABELS_PATH = ROOT / "jian_recall" / "data" / "qa_labels.json"

POOL = (
    "今天天气不错", "中午吃了碗面", "地铁上人很多", "晚上加班到九点",
    "周末想睡个懒觉", "楼下的花开了", "手机又没电了", "快递放在门口",
    "明天要早起赶车", "杯子摔碎了", "会议改到下午三点", "空调有点冷",
    "路上下起了雨", "冰箱里没有鸡蛋了", "记得交水电费", "同事换了新工位",
    "电影票买好了", "衣服该洗了", "键盘有点卡", "路上堵了半小时",
    "晚饭吃的是面", "买了双新鞋", "头有点疼", "周日去看牙",
    "院子里的猫又来了", "电话打不通", "文件传不上去", "网慢得要命",
    "咖啡洒在桌上", "想换个手机", "下班路上听了会儿歌", "楼下在装修",
    "灯坏了一盏", "又涨房租了", "公交挤不上去", "菜市场的鱼很新鲜",
    "热水器不热", "用了半年的耳机坏了", "隔壁很吵", "银行卡找不到了",
    "忘记带钥匙", "早上起晚了", "邮箱里全是广告", "朋友约了爬山",
    "想去看海", "打印纸用完了", "窗台上落了灰", "昨晚没睡好",
    "雨伞落在公司了", "忙到没吃午饭",
)

REPLACEMENTS = (
    ("我妈", "我爸"),
    ("下周", "下个月"),
    ("大黄", "小黄"),
    ("老张", "老李"),
    ("成都", "重庆"),
    ("敦煌", "洛阳"),
    ("豆豆", "圆圆"),
    ("林小满", "陈小满"),
    ("两万", "五千"),
    ("去年十月", "前年五月"),
    ("七成", "五成"),
    ("十一年", "八年"),
    ("小组长", "副组长"),
    ("第三轮", "第二轮"),
    ("八月十六", "九月初三"),
)

_BULK: Path | None = None


def qa_labels() -> list[dict[str, str]]:
    """Load the read-only 20-question evaluation set."""
    data = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    return list(data["items"])


def write_store(root: Path, events: list[tuple[str, str]]) -> None:
    """Write a valid M1-style chain of evidence events (100 per segment)."""
    folder = root / "evidence"
    folder.mkdir(parents=True, exist_ok=True)
    previous = GENESIS_PREV
    for start in range(0, len(events), 100):
        segment = f"seg-{start // 100 + 1:04d}"
        lines: list[bytes] = []
        for offset, (stamp, text) in enumerate(events[start:start + 100]):
            event = new_event(
                start + offset + 1, segment, stamp, "user", text, previous
            )
            previous = event.hash
            lines.append(event.to_line())
        (folder / f"{segment}.jsonl").write_bytes(b"".join(lines))


def append_store(root: Path, events: list[tuple[str, str]]) -> None:
    """Append events to an existing store, continuing the last segment."""
    folder = root / "evidence"
    files = sorted(folder.glob("seg-*.jsonl"))
    if not files:
        write_store(root, events)
        return
    total = 0
    for path in files:
        total += len([line for line in path.read_text(encoding="utf-8").split("\n") if line])
    last = files[-1]
    last_lines = [line for line in last.read_text(encoding="utf-8").split("\n") if line]
    previous = json.loads(last_lines[-1])["hash"]
    segment_number = int(last.stem.split("-")[1])
    segment_count = len(last_lines)
    pending: dict[Path, list[bytes]] = {}
    for stamp, text in events:
        if segment_count >= 100:
            segment_number += 1
            segment_count = 0
        total += 1
        segment_count += 1
        event = new_event(
            total, f"seg-{segment_number:04d}", stamp, "user", text, previous
        )
        previous = event.hash
        path = folder / f"seg-{segment_number:04d}.jsonl"
        pending.setdefault(path, []).append(event.to_line())
    for path, lines in pending.items():
        mode = "ab" if path.exists() else "wb"
        with path.open(mode) as handle:
            handle.write(b"".join(lines))


def near_neighbors(gold: str) -> list[str]:
    """Rewrite one entity per variant, following the spec replacement table."""
    variants: list[str] = []
    for source, target in REPLACEMENTS[:4]:
        if source in gold:
            variants.append(gold.replace(source, target, 1))
    if not variants:
        for source, target in REPLACEMENTS[4:]:
            if source in gold:
                variants.append(gold.replace(source, target, 1))
                break
    return variants


def quality_store(root: Path) -> tuple[int, int, int]:
    """Write gold + near-neighbor + 1000 distractor events.

    Gold and near-neighbor events come first so the eight most recent events
    are ordinary distractors. Returns (normal, neighbor, gold) counts.
    """
    labels = qa_labels()
    events: list[tuple[str, str]] = []
    for item in labels:
        events.append((item["ts"], item["gold"]))
    neighbor_count = 0
    for item in labels:
        for variant in near_neighbors(item["gold"]):
            events.append((item["ts"], variant))
            neighbor_count += 1
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 10, 1, tzinfo=timezone.utc)
    span = (end - start).total_seconds()
    rng = random.Random(20261029)
    normal_count = 1000
    for index in range(normal_count):
        stamp = (start + timedelta(seconds=span * index / normal_count)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        events.append((stamp, POOL[rng.randrange(len(POOL))]))
    write_store(root, events)
    return normal_count, neighbor_count, len(labels)


def write_bulk_store(root: Path, count: int = 200000) -> None:
    """Write ``count`` cheap but well-formed evidence lines for perf tests."""
    folder = root / "evidence"
    folder.mkdir(parents=True, exist_ok=True)
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 10, 1, tzinfo=timezone.utc)
    span = (end - start).total_seconds()
    rng = random.Random(20261029)
    labels = qa_labels()
    gold_positions = {
        (slot * count) // len(labels): labels[slot]["gold"]
        for slot in range(len(labels))
    }
    lines: list[str] = []
    for index in range(count):
        sequence = index + 1
        segment = index // 100 + 1
        stamp = (start + timedelta(seconds=span * index / count)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        text = gold_positions.get(index)
        if text is None:
            text = POOL[rng.randrange(len(POOL))]
        lines.append(_bulk_line(sequence, segment, stamp, text))
        if len(lines) == 100 or index == count - 1:
            (folder / f"seg-{segment:04d}.jsonl").write_text(
                "".join(lines), encoding="utf-8"
            )
            lines = []


def _bulk_line(sequence: int, segment: int, stamp: str, text: str) -> str:
    return (
        '{"ep":"seg-%04d","hash":"%s","id":"ev_%06d","prev":"%s","role":"user",'
        '"t":"%s","text":%s,"type":"turn","v":1}\n'
        % (segment, "0" * 64, sequence, "0" * 64, stamp,
           json.dumps(text, ensure_ascii=False))
    )


def bulk_store() -> Path:
    """Return a cached 200k-event store, created on first use."""
    global _BULK
    if _BULK is None:
        root = Path(tempfile.mkdtemp(prefix="jian_rc_bulk_"))
        atexit.register(shutil.rmtree, root, True)
        write_bulk_store(root)
        _BULK = root
    return _BULK
