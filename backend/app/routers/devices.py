"""GET /api/devices —— 设备清单 + 在线状态 + 最新遥测。"""
from __future__ import annotations

from fastapi import APIRouter

from .. import config, db, schemas
from ..timeutil import seconds_since

router = APIRouter(prefix="/api", tags=["devices"])


def resolve_status(last_seen: str | None) -> str:
    """last_seen 距今 > DEVICE_OFFLINE_SECONDS 即 offline；无记录按 offline。"""
    delta = seconds_since(last_seen)
    if delta is None:
        return "offline"
    return "online" if delta <= config.DEVICE_OFFLINE_SECONDS else "offline"


def build_device_items() -> list[schemas.DeviceItem]:
    items: list[schemas.DeviceItem] = []
    for row in db.list_devices():
        latest = db.latest_telemetry(row["device_code"])
        items.append(
            schemas.DeviceItem(
                device_code=row["device_code"],
                name=row["name"],
                plot_code=row["plot_code"],
                plot_name=row["plot_name"],
                type=row["type"],
                location=row["location"],
                status=resolve_status(row["last_seen"]),
                last_seen=row["last_seen"],
                latest=schemas.LatestTelemetry(**latest) if latest else None,
            )
        )
    return items


@router.get("/devices", response_model=schemas.DevicesResponse)
def get_devices() -> schemas.DevicesResponse:
    items = build_device_items()
    online = sum(1 for item in items if item.status == "online")
    return schemas.DevicesResponse(
        total=len(items), online=online, offline=len(items) - online, items=items
    )
