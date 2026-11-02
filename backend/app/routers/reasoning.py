"""Context Engineering 推演（V2_PLAN.md 第 6/7/8 节）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .. import reasoning, schemas

router = APIRouter(prefix="/api/reasoning", tags=["reasoning"])


@router.post("/simulate", response_model=schemas.ReasoningResponse)
async def post_simulate(payload: schemas.ReasoningSimulateRequest) -> schemas.ReasoningResponse:
    """真实大模型推演；无 Key/超时/非 JSON/Schema 失败一律降级，**永不 5xx**。"""
    result = await reasoning.simulate(payload.plot_code, payload.node_id)
    return schemas.ReasoningResponse(**result)


@router.get("/history", response_model=schemas.ReasoningHistoryResponse)
def get_history(limit: int = Query(20, gt=0)) -> schemas.ReasoningHistoryResponse:
    """摘要列表，**不含完整 prompt**（减体积）。必须注册在 /{reasoning_id} 之前。"""
    return schemas.ReasoningHistoryResponse(**reasoning.history(limit))


@router.get("/{reasoning_id}", response_model=schemas.ReasoningDetailResponse)
def get_detail(reasoning_id: str) -> schemas.ReasoningDetailResponse:
    """白盒回看：含 prompt 原文与模型原始返回。"""
    result = reasoning.detail(reasoning_id)
    if result is None:
        raise HTTPException(status_code=404, detail="reasoning not found")
    return schemas.ReasoningDetailResponse(**result)
