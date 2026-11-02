"""气象 Mock（V2_PLAN.md 第 6 节）。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from .. import schemas, weather

router = APIRouter(prefix="/api/weather", tags=["weather"])


@router.get("/latest", response_model=schemas.WeatherLatestResponse)
def get_latest(plot_code: str = Query("A")) -> schemas.WeatherLatestResponse:
    """最新气象 + 未来 24h 模拟预报；无数据时 latest=null（仍 200）。"""
    return schemas.WeatherLatestResponse(**weather.latest(plot_code))
