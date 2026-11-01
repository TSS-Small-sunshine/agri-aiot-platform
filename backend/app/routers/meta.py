"""GET /api/meta —— 地块、阈值、模拟器间隔（契约第 5 节）。"""
from __future__ import annotations

from fastapi import APIRouter

from .. import config, schemas

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

    return schemas.MetaResponse(
        plots=[plots[key] for key in sorted(plots)],
        thresholds=schemas.MetaThresholds(**config.meta_thresholds()),
        sim_interval_seconds=config.SIM_INTERVAL_SECONDS,
    )
