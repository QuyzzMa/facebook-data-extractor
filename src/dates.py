"""Doc ngay/gio kieu Facebook (tieng Viet + tieng Anh) va loc DataFrame theo ngay."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

VN_TZ = timezone(timedelta(hours=7))

_EN_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_VI_ABS = re.compile(
    r"(\d{1,2})\s*(?:tháng|thg)\s*(\d{1,2})(?:\s*,?\s*(\d{4}))?"
    r"(?:\s*(?:lúc|at)?\s*(\d{1,2}):(\d{2}))?",
    re.IGNORECASE,
)
_EN_ABS = re.compile(
    r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{4}))?"
    r"(?:\s*(?:at|lúc)?\s*(\d{1,2}):(\d{2})\s*(AM|PM)?)?",
    re.IGNORECASE,
)
_YESTERDAY = re.compile(
    r"(hôm qua|yesterday)(?:\s*(?:lúc|at)?\s*(\d{1,2}):(\d{2})\s*(AM|PM)?)?",
    re.IGNORECASE,
)
_VI_REL = re.compile(r"(\d+)\s*(giây|phút|giờ|ngày|tuần|tháng|năm)(?![\wÀ-ỹ])", re.IGNORECASE)
_EN_REL = re.compile(
    r"(?<![\w.])(\d+)\s?(s|m|h|d|w|y|sec|secs|min|mins|hr|hrs|hour|hours|day|days|week|weeks)\b",
    re.IGNORECASE,
)
_JUST_NOW = re.compile(r"vừa xong|vừa mới|just now", re.IGNORECASE)

_VI_UNITS = {
    "giây": timedelta(seconds=1), "phút": timedelta(minutes=1), "giờ": timedelta(hours=1),
    "ngày": timedelta(days=1), "tuần": timedelta(weeks=1),
    "tháng": timedelta(days=30), "năm": timedelta(days=365),
}
_EN_UNITS = {
    "s": timedelta(seconds=1), "sec": timedelta(seconds=1), "secs": timedelta(seconds=1),
    "m": timedelta(minutes=1), "min": timedelta(minutes=1), "mins": timedelta(minutes=1),
    "h": timedelta(hours=1), "hr": timedelta(hours=1), "hrs": timedelta(hours=1),
    "hour": timedelta(hours=1), "hours": timedelta(hours=1),
    "d": timedelta(days=1), "day": timedelta(days=1), "days": timedelta(days=1),
    "w": timedelta(weeks=1), "week": timedelta(weeks=1), "weeks": timedelta(weeks=1),
    "y": timedelta(days=365),
}


def _hour24(hour: int, ampm: str | None) -> int:
    if not ampm:
        return hour
    ampm = ampm.upper()
    if ampm == "PM" and hour < 12:
        return hour + 12
    if ampm == "AM" and hour == 12:
        return 0
    return hour


def _build(now: datetime, year, month, day, hour=0, minute=0) -> datetime | None:
    try:
        if year is None:
            candidate = datetime(now.year, month, day, hour, minute, tzinfo=now.tzinfo)
            if candidate > now + timedelta(days=1):  # chua co nam: coi la nam ngoai
                candidate = candidate.replace(year=now.year - 1)
            return candidate
        return datetime(year, month, day, hour, minute, tzinfo=now.tzinfo)
    except ValueError:
        return None


def parse_fb_datetime(text, now: datetime) -> datetime | None:
    """Tra ve datetime (cung mui gio voi `now`) hoac None neu khong doc duoc."""
    if text is None or not isinstance(text, str) or not text.strip():
        return None
    s = text.strip()

    m = _VI_ABS.search(s)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else None
        hour = int(m.group(4)) if m.group(4) else 0
        minute = int(m.group(5)) if m.group(5) else 0
        result = _build(now, year, month, day, hour, minute)
        if result:
            return result

    for m in _EN_ABS.finditer(s):
        month = _EN_MONTHS.get(m.group(1).lower())
        if not month:
            continue
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else None
        hour = _hour24(int(m.group(4)), m.group(6)) if m.group(4) else 0
        minute = int(m.group(5)) if m.group(5) else 0
        result = _build(now, year, month, day, hour, minute)
        if result:
            return result

    m = _YESTERDAY.search(s)
    if m:
        base = now - timedelta(days=1)
        hour = _hour24(int(m.group(2)), m.group(4)) if m.group(2) else 0
        minute = int(m.group(3)) if m.group(3) else 0
        return base.replace(hour=hour, minute=minute, second=0, microsecond=0)

    m = _VI_REL.search(s)
    if m:
        return now - int(m.group(1)) * _VI_UNITS[m.group(2).lower()]

    m = _EN_REL.search(s)
    if m:
        return now - int(m.group(1)) * _EN_UNITS[m.group(2).lower()]

    if _JUST_NOW.search(s):
        return now
    return None


def filter_by_date(df, column, date_from, date_to, now, keep_undated=True):
    """Loc DataFrame theo cot thoi gian. Tra ve (df_moi, thong_ke)."""
    stats = {"total": len(df), "kept": 0, "dropped_out_of_range": 0, "undated": 0}
    start = end = None
    if date_from:
        start = datetime.strptime(str(date_from).strip(), "%Y-%m-%d").replace(tzinfo=now.tzinfo)
    if date_to:
        end = datetime.strptime(str(date_to).strip(), "%Y-%m-%d").replace(
            tzinfo=now.tzinfo, hour=23, minute=59, second=59, microsecond=999999
        )
    if start and end and start > end:
        raise ValueError("date_from sau date_to")

    out = df.copy()
    if column not in out.columns:
        out["parsed_datetime"] = ""
        out["date_status"] = "undated"
        stats["undated"] = len(out)
        stats["kept"] = len(out) if keep_undated else 0
        return (out if keep_undated else out.iloc[0:0]), stats

    parsed = [parse_fb_datetime(v, now) for v in out[column]]
    out["parsed_datetime"] = [p.isoformat(timespec="minutes") if p else "" for p in parsed]
    keep = []
    status = []
    for p in parsed:
        if p is None:
            stats["undated"] += 1
            status.append("undated")
            keep.append(bool(keep_undated))
        elif (start and p < start) or (end and p > end):
            stats["dropped_out_of_range"] += 1
            status.append("out_of_range")
            keep.append(False)
        else:
            status.append("ok")
            keep.append(True)
    out["date_status"] = status
    out = out[keep].reset_index(drop=True)
    stats["kept"] = len(out)
    return out, stats
