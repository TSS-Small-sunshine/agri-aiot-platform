"""运行时配置中心（V2_PLAN.md 第 6 节）：热生效、Key 掩码、探活。"""
from __future__ import annotations

from fastapi import APIRouter

from .. import llm, runtime_config, schemas

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config", response_model=schemas.ConfigResponse)
def get_config() -> schemas.ConfigResponse:
    """只回显掩码，完整 Key 永不出现在响应体。"""
    return schemas.ConfigResponse(**runtime_config.public_view())


@router.put("/config", response_model=schemas.ConfigResponse)
def put_config(payload: schemas.ConfigUpdateRequest) -> schemas.ConfigResponse:
    """写 RUNTIME_CONFIG_PATH 并立即生效（每次调用都重新读文件，无进程内缓存）。"""
    data = runtime_config.update(payload.model_dump(exclude_unset=True))
    return schemas.ConfigResponse(**data)


@router.post("/config/test", response_model=schemas.ConfigTestResponse)
async def test_config() -> schemas.ConfigTestResponse:
    """用当前配置探活 GET {base_url}/models；失败也返回 200 + ok=false。"""
    return schemas.ConfigTestResponse(**await runtime_config.probe())


@router.get("/models", response_model=schemas.AiModelsResponse)
async def get_models() -> schemas.AiModelsResponse:
    """V2 新增路径；与 V1 的 GET /api/ai/models 同源同结构（V1 路径保留为别名）。"""
    items, error, degraded = await llm.discover_models()
    return schemas.AiModelsResponse(
        configured=llm.is_configured(),
        degraded=degraded,
        default_model=llm.default_model(),
        error=error,
        items=[schemas.ModelItem(**item) for item in items],
    )
