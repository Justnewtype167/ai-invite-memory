"""Relative time expressions (timex): A-class windows, B-class vague, C-class lunar."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from jian_cn.errors import CnError, E_CN_BAD_ANCHOR, E_CN_PARSE
from jian_cn.normalize import normalize

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

_CN_DIGIT = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
}
_NUM = r"[一二三四五六七八九十]+"
_NUM_OR_ARABIC = r"[0-9]{1,2}|[一二三四五六七八九十]+"

_R_DAY_AGO = re.compile(rf"^({_NUM})天前$")
_R_YEAR_AGO = re.compile(rf"^({_NUM})年前$")
_R_LAST_YEAR_MONTH = re.compile(rf"^去年({_NUM_OR_ARABIC})月$")
_R_BEFORE_LAST_YEAR_MONTH = re.compile(rf"^前年({_NUM_OR_ARABIC})月$")
_R_THIS_YEAR_DATE = re.compile(rf"^今年({_NUM_OR_ARABIC})月({_NUM_OR_ARABIC})日$")


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


def _month_span(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _added_months(day: date, delta: int) -> date:
    total = day.year * 12 + (day.month - 1) + delta
    year, month = divmod(total, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def _added_years(day: date, delta: int) -> date:
    year = day.year + delta
    last = calendar.monthrange(year, day.month)[1]
    return date(year, day.month, min(day.day, last))


def _month_third(day: date, part: str) -> TimeSpan:
    last = calendar.monthrange(day.year, day.month)[1]
    third = last // 3
    if part == "first":
        start, end = 1, third
    elif part == "middle":
        start, end = third + 1, 2 * third
    else:
        start, end = 2 * third + 1, last
    return TimeSpan(date(day.year, day.month, start).isoformat(),
                    date(day.year, day.month, end).isoformat(),
                    "month", "range")


def _week_span(day: date, offset: int) -> TimeSpan:
    monday = day - timedelta(days=day.weekday()) + timedelta(weeks=offset)
    return TimeSpan(monday.isoformat(), (monday + timedelta(days=6)).isoformat(),
                    "week", "range")


def _quarter_part(day: date, part: str) -> TimeSpan:
    first_month = ((day.month - 1) // 3) * 3 + 1
    month = first_month + {"first": 0, "middle": 1, "last": 2}[part]
    start, end = _month_span(day.year, month)
    return TimeSpan(start.isoformat(), end.isoformat(), "month", "range")


def _day_span(day: date) -> TimeSpan:
    return TimeSpan(day.isoformat(), day.isoformat(), "day", "exact")


def _fixed_day(day: date, month: int, day_of_month: int) -> TimeSpan:
    return _day_span(date(day.year, month, day_of_month))


def _resolve_exact(text: str, day: date) -> TimeSpan | None:
    if text in ("今天", "今晚", "今早"):
        return _day_span(day)
    if text == "昨天" or text == "昨晚":
        return _day_span(day - timedelta(days=1))
    if text == "前天":
        return _day_span(day - timedelta(days=2))
    if text == "大前天":
        return _day_span(day - timedelta(days=3))
    if text == "明天":
        return _day_span(day + timedelta(days=1))
    if text == "后天":
        return _day_span(day + timedelta(days=2))
    if text == "这周":
        return _week_span(day, 0)
    if text == "上周":
        return _week_span(day, -1)
    if text == "上上周":
        return _week_span(day, -2)
    if text == "下周":
        return _week_span(day, 1)
    if text == "月初":
        return _month_third(day, "first")
    if text == "月中":
        return _month_third(day, "middle")
    if text == "月底":
        return _month_third(day, "last")
    if text == "月初一":
        return _day_span(date(day.year, day.month, 1))
    if text == "这个月":
        start, end = _month_span(day.year, day.month)
        return TimeSpan(start.isoformat(), end.isoformat(), "month", "range")
    if text == "上个月":
        target = _added_months(date(day.year, day.month, 1), -1)
        start, end = _month_span(target.year, target.month)
        return TimeSpan(start.isoformat(), end.isoformat(), "month", "range")
    if text == "上上个月":
        target = _added_months(date(day.year, day.month, 1), -2)
        start, end = _month_span(target.year, target.month)
        return TimeSpan(start.isoformat(), end.isoformat(), "month", "range")
    if text == "下个月":
        target = _added_months(date(day.year, day.month, 1), 1)
        start, end = _month_span(target.year, target.month)
        return TimeSpan(start.isoformat(), end.isoformat(), "month", "range")
    if text == "季初":
        return _quarter_part(day, "first")
    if text == "季中":
        return _quarter_part(day, "middle")
    if text == "季度末":
        return _quarter_part(day, "last")
    if text == "年初":
        return TimeSpan(date(day.year, 1, 1).isoformat(),
                        date(day.year, 4, 30).isoformat(), "year", "range")
    if text == "年末":
        return TimeSpan(date(day.year, 9, 1).isoformat(),
                        date(day.year, 12, 31).isoformat(), "year", "range")
    if text == "今年":
        return TimeSpan(date(day.year, 1, 1).isoformat(),
                        date(day.year, 12, 31).isoformat(), "year", "range")
    if text == "去年":
        year = day.year - 1
        return TimeSpan(date(year, 1, 1).isoformat(),
                        date(year, 12, 31).isoformat(), "year", "range")
    if text == "前年":
        year = day.year - 2
        return TimeSpan(date(year, 1, 1).isoformat(),
                        date(year, 12, 31).isoformat(), "year", "range")
    if text == "明年":
        year = day.year + 1
        return TimeSpan(date(year, 1, 1).isoformat(),
                        date(year, 12, 31).isoformat(), "year", "range")
    if text == "去年这时候":
        return _day_span(_added_years(day, -1))
    if text == "半个月前":
        return _day_span(day - timedelta(days=15))
    if text == "半年前":
        return _day_span(_added_months(day, -6))
    if text == "元旦":
        return _fixed_day(day, 1, 1)
    if text == "劳动节":
        return _fixed_day(day, 5, 1)
    if text == "国庆":
        return _fixed_day(day, 10, 1)
    if text == "儿童节":
        return _fixed_day(day, 6, 1)
    return None


def _resolve_pattern(text: str, day: date) -> TimeSpan | None:
    match = _R_DAY_AGO.match(text)
    if match:
        count = _cn_number(match.group(1))
        if count is None or not 1 <= count <= 60:
            raise CnError(E_CN_PARSE, f"无法解析时间表达：{text}")
        return _day_span(day - timedelta(days=count))
    match = _R_YEAR_AGO.match(text)
    if match:
        count = _cn_number(match.group(1))
        if count is None or not 1 <= count <= 100:
            raise CnError(E_CN_PARSE, f"无法解析时间表达：{text}")
        return _day_span(_added_years(day, -count))
    match = _R_LAST_YEAR_MONTH.match(text)
    if match:
        month = _cn_number(match.group(1))
        if month is None or not 1 <= month <= 12:
            raise CnError(E_CN_PARSE, f"无法解析时间表达：{text}")
        start, end = _month_span(day.year - 1, month)
        return TimeSpan(start.isoformat(), end.isoformat(), "month", "range")
    match = _R_BEFORE_LAST_YEAR_MONTH.match(text)
    if match:
        month = _cn_number(match.group(1))
        if month is None or not 1 <= month <= 12:
            raise CnError(E_CN_PARSE, f"无法解析时间表达：{text}")
        start, end = _month_span(day.year - 2, month)
        return TimeSpan(start.isoformat(), end.isoformat(), "month", "range")
    match = _R_THIS_YEAR_DATE.match(text)
    if match:
        month = _cn_number(match.group(1))
        day_of_month = _cn_number(match.group(2))
        if month is None or day_of_month is None:
            raise CnError(E_CN_PARSE, f"无法解析时间表达：{text}")
        try:
            target = date(day.year, month, day_of_month)
        except ValueError as exc:
            raise CnError(E_CN_PARSE, f"无法解析时间表达：{text}") from exc
        return _day_span(target)
    return None


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
    span = _resolve_exact(text, day)
    if span is not None:
        return span
    span = _resolve_pattern(text, day)
    if span is not None:
        return span
    raise CnError(E_CN_PARSE, f"无法解析时间表达：{text}")
