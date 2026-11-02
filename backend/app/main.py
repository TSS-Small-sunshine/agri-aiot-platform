"""FastAPI 应用装配：lifespan（建表 + 启 MQTT）、CORS、静态托管、全部路由。"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from . import command, config, db, llm, runtime_config, schemas
from .mqtt_client import ingest
from .routers import ai, alerts, command as command_router, config as config_router
from .routers import devices, meta, reasoning as reasoning_router, shop, telemetry, weather as weather_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("agri")

STARTED_AT = time.time()


async def _command_timeout_sweeper() -> None:
    """后台清扫：超过 COMMAND_ACK_TIMEOUT_SECONDS 仍无回执的指令标 timeout。

    不新增常驻进程（V2_PLAN.md 第 0 节 2C2G 约束），只是应用内一个 asyncio 任务。
    """
    interval = max(1.0, min(5.0, float(config.COMMAND_ACK_TIMEOUT_SECONDS) or 5.0))
    while True:
        try:
            await asyncio.sleep(interval)
            await asyncio.to_thread(command.sweep_timeouts)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 —— 清扫失败不能拖垮服务
            log.exception("指令超时清扫任务异常（已忽略）")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    db.purge_old_telemetry()
    log.info("SQLite 就绪: %s (WAL)", config.DB_PATH)
    ingest.start()  # 连不上 Broker 也不会抛异常，仅降级为 disconnected
    sweeper = asyncio.create_task(_command_timeout_sweeper())
    try:
        yield
    finally:
        sweeper.cancel()
        try:
            await sweeper
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        ingest.stop()
        db.close_all()


app = FastAPI(
    title="智慧农业 AIoT 平台",
    version=config.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- API 路由（必须在静态挂载之前注册）----
app.include_router(devices.router)
app.include_router(telemetry.router)
app.include_router(alerts.router)
app.include_router(ai.router)
app.include_router(meta.router)
# ---- V2 新增路由 ----
app.include_router(config_router.router)
app.include_router(reasoning_router.router)
app.include_router(command_router.router)
app.include_router(weather_router.router)
app.include_router(shop.router)


@app.get("/api/health", response_model=schemas.HealthResponse, tags=["health"])
def get_health() -> schemas.HealthResponse:
    stats = ingest.stats()
    return schemas.HealthResponse(
        status="ok",
        version=config.APP_VERSION,
        uptime_s=round(time.time() - STARTED_AT, 1),
        db=schemas.HealthDb(ok=db.db_ok(), path=str(config.DB_PATH)),
        mqtt=schemas.HealthMqtt(
            connected=bool(stats["connected"]),
            host=config.MQTT_HOST,
            port=config.MQTT_PORT,
            topic=config.MQTT_TOPIC,
        ),
        llm=schemas.HealthLlm(
            configured=llm.is_configured(),
            # V2：base_url 来自运行时配置（runtime_config.json > 环境变量 > 内置 Mock）
            base_url=runtime_config.effective_base_url() or None,
            degraded=not llm.is_configured(),
        ),
    )


# ---- 静态资源与 SPA 回退 ----
# 资源类请求的扩展名集合：这类路径未命中时必须真 404（JSON），
# 绝不能回退 index.html —— 否则浏览器会拿到 content-type: text/html 的
# module script，按 HTML 规范因 MIME 不符拒绝执行，整页白屏。
_ASSET_EXTENSIONS = frozenset({
    ".js", ".mjs", ".cjs", ".css", ".map", ".json",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".avif",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp4", ".webm", ".wasm",
})


def _is_asset_request(normalized: str) -> bool:
    """归一化后的路径是否属于"静态资源请求"（而非页面导航）。

    frontend/vite.config.js 的 base: './' 使 index.html 用相对路径引用产物，
    所以未知深链 /nope/deep 会让浏览器去请求 /nope/assets/index-*.js ——
    这类请求必须 404 而不是回退页面。
    """
    if normalized.startswith("assets/"):
        return True
    return Path(normalized).suffix.lower() in _ASSET_EXTENSIONS


class SPAStaticFiles(StaticFiles):
    """静态资源优先；未命中的**页面导航**回退 index.html。

    注意：starlette 1.x 的 self.directory 是 str（os.fspath 后的结果），
    必须用 os.path.join 拼路径，不能直接用 / 运算符。
    /api/** 的未命中不做 SPA 回退，保持 FastAPI 标准 404 响应体。
    资源类请求（/assets/** 或带资源扩展名）同样不回退，返回真 404。
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # path 已过 os.path.normpath，Windows 下分隔符会变成 "\\"，先归一化再判断。
            normalized = path.replace("\\", "/")
            if exc.status_code == 404:
                if normalized.startswith("api/"):
                    raise
                if _is_asset_request(normalized):
                    # 资源类请求：以非 text/html 的真 404 结束，让浏览器按资源失败处理。
                    raise
                index_path = Path(self.directory) / "index.html"
                if index_path.is_file():
                    return self._navigation_response(index_path, scope)
            raise

    def _navigation_response(self, index_path: Path, scope) -> Response:
        """回退 index.html，并为多段深链注入 <base>。

        index.html 用 './assets/**' 相对路径（vite base: './'，不得改动）。
        在 /nope/deep 这类多段深链下，浏览器会把 './assets/x' 解析成
        '/nope/assets/x'，产物取不到 → 模块脚本不执行 → 整页白屏。
        注入 <base href="{应用根}/"> 后，相对路径重新解析到 /assets/**。
        仅在回退路径上注入（真实存在的 '/' 仍由 StaticFiles 原样返回），
        且不修改磁盘上的 frontend/dist/index.html。
        """
        base = scope.get("root_path") or "/"
        if not base.endswith("/"):
            base += "/"
        try:
            html = index_path.read_text(encoding="utf-8")
        except OSError:
            return FileResponse(index_path)
        if "<base " not in html:
            html = html.replace("<head>", f'<head>\n    <base href="{base}">', 1)
        return HTMLResponse(html)


INDEX_HTML = config.STATIC_DIR / "index.html"

if config.STATIC_DIR.is_dir():
    app.mount("/", SPAStaticFiles(directory=str(config.STATIC_DIR), html=True), name="static")
    log.info("静态目录已挂载: %s", config.STATIC_DIR)
else:
    log.warning("静态目录不存在（%s），/ 将返回 JSON 提示", config.STATIC_DIR)

    @app.get("/", include_in_schema=False)
    def static_missing_root():
        # 契约第 7 节：STATIC_DIR 不存在时 / 返回一行 JSON 提示，不得 500。
        return JSONResponse(
            {
                "detail": "frontend build not found",
                "hint": "请先构建前端（npm run build）并把 frontend/dist 拷贝到 STATIC_DIR",
                "static_dir": str(config.STATIC_DIR),
                "api": "/api/health",
            }
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    def static_missing_catchall(full_path: str):
        # /api/** 的未命中保持 FastAPI 标准 404，不干扰接口契约。
        if full_path.startswith("api/"):
            raise StarletteHTTPException(status_code=404, detail="Not Found")
        return JSONResponse(
            {"detail": "frontend build not found", "path": f"/{full_path}"},
            status_code=404,
        )
