"""遥测查询：latest / history / summary（契约第 5 节）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import config, db, schemas
from ..routers.devices import build_device_items
from ..timeutil import cutoff_iso

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

# limit 取"最近 N 条"（内层 DESC），再按契约要求升序返回（外层 ASC）。
_HISTORY_SQL = """
SELECT ts, temperature, humidity, soil_moisture, soil_temp FROM (
  SELECT ts, temperature, humidity, soil_moisture, soil_temp
  FROM telemetry
  WHERE device_code = ? AND ts >= ?
  ORDER BY ts DESC, id DESC
  LIMIT ?
) ORDER BY ts ASC
"""

_STAT_SQL = """
SELECT COUNT(*) AS samples,
       AVG(temperature) AS t_avg, MIN(temperature) AS t_min, MAX(temperature) AS t_max,
       AVG(humidity)    AS h_avg, MIN(humidity)    AS h_min, MAX(humidity)    AS h_max,
       AVG(soil_moisture) AS s_avg, MIN(soil_moisture) AS s_min, MAX(soil_moisture) AS s_max
FROM telemetry
WHERE ts >= ?
"""


def _round(value) -> float | None:
    return None if value is None else round(float(value), 1)


def _hours(value: float) -> int | float:
    """契约示例里 hours 是整数（24/1）；整数值按 int 输出，否则保留小数。"""
    return int(value) if float(value).is_integer() else float(value)


def _block(avg, mn, mx) -> schemas.StatBlock:
    return schemas.StatBlock(avg=_round(avg), min=_round(mn), max=_round(mx))


@router.get("/latest", response_model=schemas.TelemetryLatestResponse)
def get_latest() -> schemas.TelemetryLatestResponse:
    items = []
    for device in build_device_items():
        if device.latest is None:
            continue
        items.append(
            schemas.TelemetryLatestItem(
                device_code=device.device_code,
                plot_code=device.plot_code,
                **device.latest.model_dump(),
            )
        )
    return schemas.TelemetryLatestResponse(items=items)


@router.get("/history", response_model=schemas.TelemetryHistoryResponse)
def get_history(
    device_code: str = Query(..., min_length=1),
    hours: float = Query(1, gt=0),
    limit: int = Query(720, gt=0),
) -> schemas.TelemetryHistoryResponse:
    hours = min(hours, float(config.HISTORY_HOURS_MAX))
    limit = min(limit, 5000)

    known = db.query_one("SELECT device_code FROM devices WHERE device_code = ?", (device_code,))
    if known is None:
        raise HTTPException(status_code=404, detail="device not found")

    rows = db.query(_HISTORY_SQL, (device_code, cutoff_iso(hours), limit))
    points = [schemas.HistoryPoint(**row) for row in rows]
    return schemas.TelemetryHistoryResponse(
        device_code=device_code, hours=_hours(hours), count=len(points), points=points
    )


@router.get("/summary", response_model=schemas.TelemetrySummaryResponse)
def get_summary(hours: float = Query(24, gt=0)) -> schemas.TelemetrySummaryResponse:
    hours = min(hours, float(config.HISTORY_HOURS_MAX))
    row = db.query_one(_STAT_SQL, (cutoff_iso(hours),)) or {}
    return schemas.TelemetrySummaryResponse(
        hours=_hours(hours),
        samples=int(row.get("samples") or 0),
        temperature=_block(row.get("t_avg"), row.get("t_min"), row.get("t_max")),
        humidity=_block(row.get("h_avg"), row.get("h_min"), row.get("h_max")),
        soil_moisture=_block(row.get("s_avg"), row.get("s_min"), row.get("s_max")),
    )
