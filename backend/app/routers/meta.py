"""GET /api/meta —— 地块、阈值、模拟器间隔（契约第 5 节）+ V2 扩展段。

V2 扩展（V2_PLAN.md 第 6 节）：plots[] 增加 {col,row,crop,area_mu,stage}；
新增 crops 段（作物清单）与 weather 段（气象 Mock 元信息）。
V1 已有字段（plots[].plot_code/plot_name/devices、thresholds、sim_interval_seconds）逐字不变。
"""
from __future__ import annotations

from fastapi import APIRouter

from .. import config, schemas, weather

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/meta", response_model=schemas.MetaResponse)
def get_meta() -> schemas.MetaResponse:
    plots: dict[str, schemas.MetaPlot] = {}
    for device in config.DEVICES:
        plot = plots.get(device["plot_code"])
        if plot is None:
            plot = schemas.MetaPlot(
                plot_code=device["plot_code"], plot_name=device["plot_name"], devices=[]
            )
            plots[device["plot_code"]] = plot
        plot.devices.append(device["device_code"])

    # V2：补 2.5D 网格坐标、作物、面积、物候期（来自 config.PLOTS）
    for code, plot in plots.items():
        meta = config.PLOT_BY_CODE.get(code) or {}
        plot.name = meta.get("name")
        plot.crop = meta.get("crop")
        plot.area_mu = meta.get("area_mu")
        plot.stage = meta.get("stage")
        plot.col = meta.get("col")
        plot.row = meta.get("row")

    # 气象段：各试验地块最新观测（无数据时 items 为空，不报错）
    weather_items = []
    for code in sorted(plots):
        latest = weather.context_snapshot(code)
        if latest:
            weather_items.append(schemas.WeatherPoint(**latest))

    return schemas.MetaResponse(
        plots=[plots[key] for key in sorted(plots)],
        thresholds=schemas.MetaThresholds(**config.meta_thresholds()),
        sim_interval_seconds=config.SIM_INTERVAL_SECONDS,
        crops=[schemas.MetaCrop(**crop) for crop in config.CROPS],
        weather=schemas.MetaWeather(
            interval_seconds=int(config.WEATHER_INTERVAL_SECONDS),
            topic=config.MQTT_WEATHER_TOPIC,
            items=weather_items,
        ),
    )
