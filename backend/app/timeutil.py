"""时间助手：全系统统一 ISO8601 带时区字符串（契约第 4 节）。

所有写入的 ts 都归一化到本机时区，保证同一列内偏移量一致 —— 这样 SQLite 里
按字符串比较时间范围（ts >= cutoff）才是正确的。
"""
from __future__ import annotations

from datetime import datetime, timedelta

LOCAL_TZ = datetime.now().astimezone().tzinfo


def now() -> datetime:
    return datetime.now(LOCAL_TZ)


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(LOCAL_TZ).replace(microsecond=0).isoformat()


def now_iso() -> str:
    return to_iso(now())


def parse_iso(value) -> datetime | None:
    """宽松解析：失败返回 None，绝不抛异常（MQTT 来的脏数据不能打挂服务）。"""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt.replace(tzinfo=LOCAL_TZ) if dt.tzinfo is None else dt


def normalize_iso(value, fallback_now: bool = True) -> str | None:
    dt = parse_iso(value)
    if dt is None:
        return now_iso() if fallback_now else None
    return to_iso(dt)


def cutoff_iso(hours: float) -> str:
    return to_iso(now() - timedelta(hours=hours))


def seconds_since(iso_value) -> float | None:
    dt = parse_iso(iso_value)
    return None if dt is None else (now() - dt).total_seconds()
