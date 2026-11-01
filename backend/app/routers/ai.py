"""AI 对话：模型发现 / 对话（无 Key 自动降级）/ 历史（契约第 5 节）。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from .. import config, db, llm, schemas
from ..timeutil import now_iso

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/models", response_model=schemas.AiModelsResponse)
async def get_models() -> schemas.AiModelsResponse:
    items, error, degraded = await llm.discover_models()
    return schemas.AiModelsResponse(
        configured=llm.is_configured(),
        degraded=degraded,
        default_model=llm.default_model(),
        error=error,
        items=[schemas.ModelItem(**item) for item in items],
    )


@router.post("/chat", response_model=schemas.ChatResponse)
async def post_chat(payload: schemas.ChatRequest) -> schemas.ChatResponse:
    requested = (payload.model or "").strip() or None
    # 请求的是 mock 模型时直接走本地知识库，避免无谓的远程调用。
    if requested and requested.startswith("mock-"):
        import time
        started = time.perf_counter()
        result = llm.ChatResult(
            answer=llm.mock_answer(payload.question),
            model=requested,
            degraded=True,
            latency_ms=int((time.perf_counter() - started) * 1000),
            error="已按请求使用 Mock 模型（离线演示）",
        )
    else:
        result = await llm.chat(payload.question, requested)

    created_at = now_iso()
    chat_id = db.insert(
        """INSERT INTO ai_chat
           (session_id, question, answer, model, degraded, latency_ms, prompt_tokens, completion_tokens, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            payload.session_id, payload.question, result.answer, result.model,
            1 if result.degraded else 0, result.latency_ms,
            result.prompt_tokens, result.completion_tokens, created_at,
        ),
    )
    return schemas.ChatResponse(
        answer=result.answer,
        model=result.model,
        degraded=result.degraded,
        latency_ms=result.latency_ms,
        session_id=payload.session_id,
        created_at=created_at,
        error=result.error,
    )


@router.get("/history", response_model=schemas.ChatHistoryResponse)
def get_history(limit: int = Query(20, gt=0)) -> schemas.ChatHistoryResponse:
    limit = min(limit, config.AI_HISTORY_LIMIT)
    total = db.query_one("SELECT COUNT(*) AS c FROM ai_chat")["c"]
    rows = db.query(
        """SELECT id, question, answer, model, degraded, latency_ms, created_at
           FROM ai_chat ORDER BY created_at DESC, id DESC LIMIT ?""",
        (limit,),
    )
    return schemas.ChatHistoryResponse(
        total=int(total), items=[schemas.ChatHistoryItem(**row) for row in rows]
    )
