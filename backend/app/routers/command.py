"""指令闭环（V2_PLAN.md 第 6/9 节）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import command, config, schemas

router = APIRouter(prefix="/api/command", tags=["command"])


@router.post("/execute", response_model=schemas.CommandExecuteResponse)
def post_execute(payload: schemas.CommandExecuteRequest) -> schemas.CommandExecuteResponse:
    """落库 status=dispatched + publish agri/command/{plot}/{device} QoS1，立即返回。

    V2.1 C-9：未知地块 404、未知设备 422 —— 绝不对不存在的对象"假装下发成功"。
    """
    if payload.plot_code not in config.PLOT_BY_CODE:
        raise HTTPException(status_code=404, detail="plot not found")
    if payload.device_code not in config.DEVICE_BY_CODE:
        raise HTTPException(status_code=422, detail="device not found")
    return schemas.CommandExecuteResponse(**command.execute(payload.model_dump()))


@router.get("/history", response_model=schemas.CommandHistoryResponse)
def get_history(limit: int = Query(20, gt=0)) -> schemas.CommandHistoryResponse:
    """指令历史与状态流转（dispatched / executed / failed / timeout）。"""
    return schemas.CommandHistoryResponse(**command.history(limit))
