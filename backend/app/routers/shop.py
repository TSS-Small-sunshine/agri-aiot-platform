"""农资商城 Mock（V2_PLAN.md 第 6 节）。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from .. import db, schemas

router = APIRouter(prefix="/api/shop", tags=["shop"])


@router.get("/skus", response_model=schemas.SkuListResponse)
def get_skus(keyword: str | None = Query(None)) -> schemas.SkuListResponse:
    """按 keywords/name/description/category 模糊匹配（启动时已幂等 seed 6 条）。"""
    rows = db.list_skus(keyword)
    return schemas.SkuListResponse(
        total=len(rows),
        keyword=keyword or None,
        items=[schemas.SkuItem(**dict(row)) for row in rows],
    )
