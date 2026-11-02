"""运行时配置中心（V2_PLAN.md 第 4 节）。

优先级：runtime_config.json > 环境变量 > 内置 Mock。
文件读写都在**每次调用时**进行，因此 PUT /api/config 写盘后立刻热生效，
不需要重启进程（也没有进程内缓存 —— 这是"热生效"的实现代价，可接受）。

安全铁律（任务书第 3 节第 3 条）：
- 完整 api_key 只允许出现在 runtime_config.json 文件里；
- 任何对外结构一律走 mask_key()，形如 sk-****abcd；
- 日志里也只打印掩码。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

from . import config

log = logging.getLogger("agri.runtime_config")

SOURCE_RUNTIME = "runtime"
SOURCE_ENV = "env"
SOURCE_MOCK = "mock"

FIELDS = ("base_url", "api_key", "model")


def _read_file() -> dict:
    """读 runtime_config.json；不存在/损坏一律当作空配置，绝不抛异常。"""
    path = Path(config.RUNTIME_CONFIG_PATH)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 —— 坏文件不能让服务起不来
        log.warning("运行时配置文件无法解析（%s）：%s", path, exc)
        return {}
    if not isinstance(raw, dict):
        log.warning("运行时配置文件不是对象（%s），已忽略", path)
        return {}
    return {k: raw.get(k) for k in FIELDS if k in raw}


def _write_file(data: dict) -> None:
    path = Path(config.RUNTIME_CONFIG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: data.get(k) for k in FIELDS}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def mask_key(api_key: str | None) -> str | None:
    """sk-abcdefghijklmnop -> sk-****mnop；短 Key 只留尾部，绝不回显中间段。"""
    if not api_key:
        return None
    text = str(api_key)
    if len(text) <= 8:
        return "****"
    prefix = text[:3] if text.startswith("sk-") else text[:2]
    return f"{prefix}****{text[-4:]}"


def resolve() -> dict:
    """返回当前生效配置 + 来源。api_key 是**完整值**，仅供内部调用方使用。"""
    file_data = _read_file()
    effective: dict = {}
    source = SOURCE_MOCK

    for field in FIELDS:
        value = file_data.get(field)
        if isinstance(value, str) and value.strip():
            effective[field] = value.strip().rstrip("/") if field == "base_url" else value.strip()
            source = SOURCE_RUNTIME
            continue
        env_value = {
            "base_url": config.OPENAI_BASE_URL,
            "api_key": config.OPENAI_API_KEY,
            "model": config.OPENAI_MODEL,
        }[field]
        if env_value:
            effective[field] = env_value
            if source != SOURCE_RUNTIME:
                source = SOURCE_ENV

    effective["source"] = source
    effective["path"] = str(config.RUNTIME_CONFIG_PATH)
    effective["configured"] = bool(effective.get("base_url") and effective.get("api_key"))
    effective["model"] = effective.get("model") or None
    return effective


def effective_base_url() -> str:
    return resolve().get("base_url") or ""


def effective_api_key() -> str:
    return resolve().get("api_key") or ""


def is_configured() -> bool:
    return bool(resolve()["configured"])


def default_model() -> str:
    """未显式配置模型时回落 Mock 模型 id（与 V1 行为一致）。"""
    return resolve().get("model") or "mock-agronomist"


def public_view() -> dict:
    """GET /api/config 的对外结构 —— 只有掩码，绝无完整 Key。"""
    data = resolve()
    return {
        "base_url": data.get("base_url") or None,
        "api_key_masked": mask_key(data.get("api_key")),
        "model": data.get("model"),
        "configured": bool(data["configured"]),
        "source": data["source"],
        "path": data["path"],
    }


def update(payload: dict) -> dict:
    """PUT /api/config：写盘并返回最新对外结构。

    语义（V2_PLAN.md 第 6 节）：api_key 传空串/缺省 = 保持不变，传 null = 清除。
    """
    current = _read_file()
    merged = {k: current.get(k) for k in FIELDS}

    for field in ("base_url", "model"):
        if field in payload:
            value = payload.get(field)
            merged[field] = value.strip() if isinstance(value, str) and value.strip() else None

    if "api_key" in payload:
        value = payload.get("api_key")
        # 缺省（键不存在）已在循环外；键存在时：None = 清除，"" = 保持不变，其余 = 覆盖。
        if value is None:
            merged["api_key"] = None
        elif isinstance(value, str) and value.strip() == "":
            pass  # 空串：保持不变
        elif isinstance(value, str):
            merged["api_key"] = value.strip()

    _write_file(merged)
    log.info(
        "运行时配置已更新：base_url=%s api_key=%s model=%s",
        merged.get("base_url"), mask_key(merged.get("api_key")), merged.get("model"),
    )
    return public_view()


async def probe() -> dict:
    """POST /api/config/test：用当前配置探活 {base_url}/models。任何异常都收敛成 ok=false。"""
    data = resolve()
    base_url = data.get("base_url")
    if not base_url:
        return {"ok": False, "latency_ms": 0, "models": [], "error": "base_url 未配置"}

    headers = {"Content-Type": "application/json"}
    if data.get("api_key"):
        headers["Authorization"] = f"Bearer {data['api_key']}"

    url = f"{base_url}/models"
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=config.OPENAI_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        latency = int((time.perf_counter() - started) * 1000)
        raw_items = body.get("data") if isinstance(body, dict) else None
        models: list[str] = []
        if isinstance(raw_items, list):
            for entry in raw_items:
                if isinstance(entry, dict) and entry.get("id"):
                    models.append(str(entry["id"]))
                elif isinstance(entry, str):
                    models.append(entry)
        return {"ok": True, "latency_ms": latency, "models": models, "error": None}
    except Exception as exc:  # noqa: BLE001 —— 探活失败必须 200，不得 5xx
        latency = int((time.perf_counter() - started) * 1000)
        return {
            "ok": False,
            "latency_ms": latency,
            "models": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
