"""Relative time expressions: primitive composition plus vague/lunar classes.

The parser is a small grammar over four primitive groups (number, class word,
level, edge), so unseen combinations such as 两年前 / 下下周 / 上季度末 /
明年初 resolve without any per-expression branch.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from aiinvite.cn.errors import CnError, E_CN_BAD_ANCHOR, E_CN_PARSE
from aiinvite.cn.normalize import normalize

_TZ = timezone(timedelta(hours=8))

_GRANULARITIES = frozenset({"day", "week", "month", "season", "year", "event"})
_CERTAINTIES = frozenset({"exact", "range", "vague", "unknown"})

_LUNAR_TOKENS = ("春节", "元宵", "端午", "中秋", "重阳", "清明")

_VAGUE: dict[str, tuple[str, str]] = {
    "春节前": ("season", "vague"),
    "春节后": ("season", "vague"),
    "秋收后": ("season", "vague"),
    "入冬前": ("season", "vague"),
    "过了年": ("year", "vague"),
    "年底前": ("year", "vague"),
    "最近": ("day", "vague"),
    "那阵子": ("day", "vague"),
    "前几天": ("day", "vague"),
    "过几天": ("day", "vague"),
    "等孩子高考完": ("event", "unknown"),
    "等我出院": ("event", "unknown"),
    "等我退伍": ("event", "unknown"),
}

# Fixed public holidays: month and day inside the anchor year.
_HOLIDAYS: dict[str, tuple[int, int]] = {
    "元旦": (1, 1),
    "劳动节": (5, 1),
    "国庆": (10, 1),
    "儿童节": (6, 1),
}

_SPECIAL = {"月初一"}

_CN_DIGIT = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
}

_NUM_PAT = r"(?:[0-9]{1,2}|[一二三四五六七八九十]+|两|半)"
_LEVEL_PAT = r"(?:大前|大后|上上|下下|今|明|去|前|昨|后|上|下|这)"
_CLASS_PAT = r"(?:个?月|个?季度|个?季|星期|礼拜|周|天|日|晚|早|年)"
_EDGE_PAT = r"[初中末底]"
_DIR_PAT = r"[前后]"

_P_OFFSET = re.compile(rf"^({_NUM_PAT})({_CLASS_PAT})({_DIR_PAT})$")
_P_YEAR_MD = re.compile(rf"^({_LEVEL_PAT})年({_NUM_PAT})月({_NUM_PAT})日$")
_P_YEAR_M = re.compile(rf"^({_LEVEL_PAT})年({_NUM_PAT})月$")
_P_YEAR_THIS = re.compile(rf"^({_LEVEL_PAT})年这时候$")
_P_EDGE = re.compile(rf"^({_LEVEL_PAT})?({_CLASS_PAT})({_EDGE_PAT})$")
_P_PERIOD = re.compile(rf"^({_LEVEL_PAT})({_CLASS_PAT})$")

_LEVEL_OFFSET = {
    "大前": -3, "大后": 3, "上上": -2, "上": -1, "去": -1, "这": 0, "今": 0,
    "昨": -1, "下": 1, "明": 1, "下下": 2, "前": -2, "后": 2,
}

_WEEK_CLASSES = {"周", "星期", "礼拜"}
_MONTH_CLASSES = {"个月", "月"}
_QUARTER_CLASSES = {"季度", "季"}
_DAY_CLASSES = {"天", "日", "早", "晚"}

# Which level words may combine with which class word.
_LEVEL_BY_CLASS: dict[str, set[str]] = {
    "天": {"今", "昨", "前", "大前", "明", "后", "大后"},
    "日": {"今", "昨", "前", "大前", "明", "后", "大后"},
    "早": {"今", "昨"},
    "晚": {"今", "昨"},
    "周": {"上上", "上", "这", "下", "下下"},
    "星期": {"上上", "上", "这", "下", "下下"},
    "礼拜": {"上上", "上", "这", "下", "下下"},
    "个月": {"上上", "上", "这", "下", "下下"},
    "月": {"上上", "上", "这", "下", "下下"},
    "季度": {"上上", "上", "这", "下", "下下"},
    "季": {"上上", "上", "这", "下", "下下"},
    "年": {"今", "明", "去", "前", "大前", "后", "大后"},
}

_EDGE_CLASSES = {"个月", "月", "年", "季度", "季"}


def _class_key(cls: str) -> str:
    """Drop a leading 个 so 这个季度末 and 一个月后 share one class table."""
    return cls[1:] if cls.startswith("个") else cls


@dataclass(frozen=True)
class TimeSpan:
    """One resolved time expression; start/end are ISO dates or None."""

    start: str | None
    end: str | None
    granularity: str
    certainty: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly view."""
        return {
            "start": self.start,
            "end": self.end,
            "granularity": self.granularity,
            "certainty": self.certainty,
        }


def _fail(text: str) -> CnError:
    return CnError(E_CN_PARSE, f"无法解析时间表达：{text}")


def _anchor_date(anchor: str | None) -> date:
    if anchor is None:
        raise CnError(E_CN_BAD_ANCHOR, "锚点时间缺失，请提供带时区的 ISO 8601 时间")
    try:
        moment = datetime.fromisoformat(anchor)
    except ValueError as exc:
        raise CnError(E_CN_BAD_ANCHOR, f"锚点时间无法解析：{anchor}") from exc
    if moment.tzinfo is None:
        raise CnError(E_CN_BAD_ANCHOR, f"锚点时间没有时区：{anchor}")
    return moment.astimezone(_TZ).date()


def _cn_number(text: str) -> int | None:
    """Parse a Chinese numeral 1-99; return None when not canonical."""
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if "十" in text:
        parts = text.split("十")
        if len(parts) != 2:
            return None
        tens = 1 if parts[0] == "" else _CN_DIGIT.get(parts[0])
        if tens is None:
            return None
        tail = parts[1]
        if tail == "":
            ones = 0
        elif len(tail) == 1 and tail in _CN_DIGIT:
            ones = _CN_DIGIT[tail]
        else:
            return None
        return tens * 10 + ones
    if len(text) == 1:
        return _CN_DIGIT.get(text)
    return None


def _number(text: str) -> tuple[str, int]:
    """Return ("int", n) or ("half", 0); raise E_CN_PARSE when not a number."""
    if text == "两":
        return "int", 2
    if text == "半":
        return "half", 0
    value = _cn_number(text)
    if value is None or not 1 <= value <= 99:
        raise _fail(text)
    return "int", value


def _month_span(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _added_months(day: date, delta: int) -> date:
    total = day.year * 12 + (day.month - 1) + delta
    year, month_index = divmod(total, 12)
    month = month_index + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def _added_years(day: date, delta: int) -> date:
    year = day.year + delta
    last = calendar.monthrange(year, day.month)[1]
    return date(year, day.month, min(day.day, last))


def _day_span(day: date) -> TimeSpan:
    return TimeSpan(day.isoformat(), day.isoformat(), "day", "exact")


def _week_span(day: date, offset: int) -> TimeSpan:
    monday = day - timedelta(days=day.weekday()) + timedelta(weeks=offset)
    return TimeSpan(monday.isoformat(), (monday + timedelta(days=6)).isoformat(),
                    "week", "range")


def _range_span(start: date, end: date, granularity: str) -> TimeSpan:
    return TimeSpan(start.isoformat(), end.isoformat(), granularity, "range")


def _quarter_first_month(year: int, month: int, offset: int = 0) -> tuple[int, int]:
    """Return the first month of the quarter containing ``month`` plus ``offset``."""
    first = ((month - 1) // 3) * 3 + 1
    total = year * 12 + (first - 1) + 3 * offset
    out_year, month_index = divmod(total, 12)
    return out_year, month_index + 1


def _month_edge(year: int, month: int, edge: str) -> TimeSpan:
    last = calendar.monthrange(year, month)[1]
    third = last // 3
    edges = {
        "初": (1, third),
        "中": (third + 1, 2 * third),
        "末": (2 * third + 1, last),
        "底": (2 * third + 1, last),
    }
    start, end = edges[edge]
    return _range_span(date(year, month, start), date(year, month, end), "month")


def _year_edge(year: int, edge: str) -> TimeSpan:
    windows = {
        "初": (1, 4),
        "中": (5, 8),
        "末": (9, 12),
        "底": (10, 12),
    }
    first, last = windows[edge]
    return _range_span(date(year, first, 1),
                       date(year, last, calendar.monthrange(year, last)[1]),
                       "year")


def _quarter_edge(year: int, month: int, offset: int, edge: str) -> TimeSpan:
    q_year, q_first = _quarter_first_month(year, month, offset)
    month = q_first + {"初": 0, "中": 1, "末": 2, "底": 2}[edge]
    start, end = _month_span(q_year, month)
    return _range_span(start, end, "month")


def _period_span(day: date, level: str, cls: str) -> TimeSpan:
    allowed = _LEVEL_BY_CLASS.get(cls)
    if not allowed or level not in allowed:
        raise _fail(f"{level}{cls}")
    offset = _LEVEL_OFFSET[level]
    if cls in _DAY_CLASSES:
        return _day_span(day + timedelta(days=offset))
    if cls in _WEEK_CLASSES:
        return _week_span(day, offset)
    if cls in _MONTH_CLASSES:
        target = _added_months(date(day.year, day.month, 1), offset)
        start, end = _month_span(target.year, target.month)
        return _range_span(start, end, "month")
    if cls in _QUARTER_CLASSES:
        q_year, q_first = _quarter_first_month(day.year, day.month, offset)
        start, _ = _month_span(q_year, q_first)
        _, end = _month_span(q_year, q_first + 2)
        return _range_span(start, end, "season")
    if cls == "年":
        year = day.year + offset
        return _range_span(date(year, 1, 1), date(year, 12, 31), "year")
    raise _fail(f"{level}{cls}")


def _edge_span(day: date, level: str | None, cls: str, edge: str) -> TimeSpan:
    if cls not in _EDGE_CLASSES:
        raise _fail(f"{cls}{edge}")
    if level is None:
        offset = 0
    else:
        allowed = _LEVEL_BY_CLASS.get(cls)
        if not allowed or level not in allowed:
            raise _fail(f"{level}{cls}{edge}")
        offset = _LEVEL_OFFSET[level]
    if cls in _MONTH_CLASSES:
        target = _added_months(date(day.year, day.month, 1), offset)
        return _month_edge(target.year, target.month, edge)
    if cls == "年":
        return _year_edge(day.year + offset, edge)
    return _quarter_edge(day.year, day.month, offset, edge)


def _offset_span(day: date, number: str, cls: str, direction: str, text: str) -> TimeSpan:
    kind, value = _number(number)
    sign = -1 if direction == "前" else 1
    if kind == "half":
        if cls in _MONTH_CLASSES:
            return _day_span(day + timedelta(days=15 * sign))
        if cls == "年":
            return _day_span(_added_months(day, 6 * sign))
        raise _fail(text)
    if cls in ("天", "日"):
        return _day_span(day + timedelta(days=value * sign))
    if cls in _WEEK_CLASSES:
        return _day_span(day + timedelta(days=7 * value * sign))
    if cls in _MONTH_CLASSES:
        return _day_span(_added_months(day, value * sign))
    if cls == "年":
        return _day_span(_added_years(day, value * sign))
    raise _fail(text)


def _year_month(day: date, level: str, number: str, text: str) -> TimeSpan:
    if level not in _LEVEL_BY_CLASS["年"]:
        raise _fail(text)
    kind, value = _number(number)
    if kind != "int" or not 1 <= value <= 12:
        raise _fail(text)
    year = day.year + _LEVEL_OFFSET[level]
    start, end = _month_span(year, value)
    return _range_span(start, end, "month")


def _year_month_day(day: date, level: str, month_text: str, day_text: str,
                    text: str) -> TimeSpan:
    if level not in _LEVEL_BY_CLASS["年"]:
        raise _fail(text)
    kind_m, month = _number(month_text)
    kind_d, day_of_month = _number(day_text)
    if kind_m != "int" or kind_d != "int":
        raise _fail(text)
    try:
        target = date(day.year + _LEVEL_OFFSET[level], month, day_of_month)
    except ValueError as exc:
        raise _fail(text) from exc
    return _day_span(target)


def _year_this_time(day: date, level: str, text: str) -> TimeSpan:
    if level not in _LEVEL_BY_CLASS["年"]:
        raise _fail(text)
    return _day_span(_added_years(day, _LEVEL_OFFSET[level]))


def parse_time(expr: str, anchor: str | None = None) -> TimeSpan:
    """Resolve a Chinese time expression against a timezone-aware anchor."""
    day = _anchor_date(anchor)
    text = normalize(expr).replace(" ", "")
    if not text:
        raise CnError(E_CN_PARSE, "空时间表达无法解析")
    if text in _VAGUE:
        granularity, certainty = _VAGUE[text]
        return TimeSpan(None, None, granularity, certainty)
    if any(token in text for token in _LUNAR_TOKENS):
        raise CnError(E_CN_PARSE, f"农历/节气表达 M2 不支持：{text}")
    if text in _SPECIAL:
        return _day_span(date(day.year, day.month, 1))
    if text in _HOLIDAYS:
        month, day_of_month = _HOLIDAYS[text]
        return _day_span(date(day.year, month, day_of_month))

    match = _P_YEAR_MD.match(text)
    if match:
        return _year_month_day(day, match.group(1), match.group(2), match.group(3), text)
    match = _P_YEAR_M.match(text)
    if match:
        return _year_month(day, match.group(1), match.group(2), text)
    match = _P_YEAR_THIS.match(text)
    if match:
        return _year_this_time(day, match.group(1), text)
    match = _P_OFFSET.match(text)
    if match:
        return _offset_span(day, match.group(1), _class_key(match.group(2)),
                            match.group(3), text)
    match = _P_EDGE.match(text)
    if match:
        return _edge_span(day, match.group(1), _class_key(match.group(2)),
                          match.group(3))
    match = _P_PERIOD.match(text)
    if match:
        return _period_span(day, match.group(1), _class_key(match.group(2)))
    raise _fail(text)
