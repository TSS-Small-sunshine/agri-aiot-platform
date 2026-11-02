"""气象数据：最新观测 + 未来 24h 模拟预报（V2_PLAN.md 第 6 节）。

数据来源：模拟器发布 agri/weather/{plot_code} → mqtt_client 落 weather 表。
预报无第三方数据源，用最新观测为锚点做确定性日变化推演（source="mock"），
保证前端在离线演示时也有 24h 曲线可渲染。
"""
from __future__ import annotations

import logging
import math
from datetime import timedelta

from . import config, db
from .timeutil import now, to_iso

log = logging.getLogger("agri.weather")

SOURCE_OBSERVED = "observed"
SOURCE_MOCK = "mock"
SOURCE_NONE = "none"

# 风向按小时在 8 个方位上循环，确定性（同一天同一小时结果一致）。
_WIND_DIRS = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]


def _round(value, digits: int = 1):
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _row_to_point(row) -> dict:
    return {
        "ts": row["ts"],
        "temperature": _round(row["temperature"]),
        "humidity": _round(row["humidity"]),
        "rainfall_mm": _round(row["rainfall_mm"]),
        "wind_dir": row["wind_dir"],
        "wind_level": row["wind_level"],
        "condition": row["condition"],
    }


def _forecast(anchor: dict) -> list[dict]:
    """以最新观测为锚点，生成未来 WEATHER_FORECAST_HOURS 小时逐时预报。"""
    base_temp = _round(anchor.get("temperature")) or 26.0
    base_hum = _round(anchor.get("humidity")) or 65.0
    base_rain = _round(anchor.get("rainfall_mm")) or 0.0
    base_wind = anchor.get("wind_level") or 2

    started = now().replace(minute=0, second=0, microsecond=0)
    points: list[dict] = []
    for hour in range(1, int(config.WEATHER_FORECAST_HOURS) + 1):
        moment = started + timedelta(hours=hour)
        # 日变化：15 时最热、3 时最冷。
        diurnal = math.cos((moment.hour - 15) / 24.0 * 2 * math.pi)
        temp = base_temp + 5.0 * diurnal
        hum = base_hum - 18.0 * diurnal
        rain = max(0.0, base_rain + (1.8 if moment.hour in (14, 15, 16) and base_hum > 78 else 0.0))
        wind = max(0, min(6, int(round(base_wind + 1.2 * math.sin(moment.hour / 24.0 * 2 * math.pi)))))
        if rain >= 2.0:
            condition = "中雨"
        elif rain > 0.0:
            condition = "小雨"
        elif hum > 85:
            condition = "阴"
        else:
            condition = "晴"
        points.append({
            "ts": to_iso(moment),
            "temperature": _round(temp),
            "humidity": _round(max(15.0, min(99.0, hum))),
            "rainfall_mm": _round(rain),
            "wind_dir": _WIND_DIRS[moment.hour % len(_WIND_DIRS)],
            "wind_level": wind,
            "condition": condition,
        })
    return points


def latest(plot_code: str) -> dict:
    """GET /api/weather/latest 的数据组装。永远返回 200（无数据时 latest=null）。"""
    row = db.latest_weather(plot_code)
    total = db.query_one(
        "SELECT COUNT(*) AS c FROM weather WHERE plot_code = ?", (plot_code,)
    )["c"]

    if row is None:
        return {
            "plot_code": plot_code,
            "latest": None,
            "forecast": [],
            "count": 0,
            "interval_seconds": int(config.WEATHER_INTERVAL_SECONDS),
            "source": SOURCE_NONE,
        }

    anchor = _row_to_point(row)
    return {
        "plot_code": plot_code,
        "latest": anchor,
        "forecast": _forecast(anchor),
        "count": int(total),
        "interval_seconds": int(config.WEATHER_INTERVAL_SECONDS),
        "source": SOURCE_OBSERVED,
    }


def context_snapshot(plot_code: str) -> dict | None:
    """给 reasoning.build_context 用的最新气象（无数据返回 None）。"""
    row = db.latest_weather(plot_code)
    if row is None:
        return None
    return _row_to_point(row)
