"""FastAPI 应用装配：lifespan（建表 + 启 MQTT）、CORS、静态托管、全部路由。"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config, db, llm, schemas
from .mqtt_client import ingest
from .routers import ai, alerts, devices, meta, telemetry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("agri")

STARTED_AT = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    db.purge_old_telemetry()
    log.info("SQLite 就绪: %s (WAL)", config.DB_PATH)
    ingest.start()  # 连不上 Broker 也不会抛异常，仅降级为 disconnected
    try:
        yield
    finally:
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
            base_url=config.OPENAI_BASE_URL or None,
            degraded=not llm.is_configured(),
        ),
    )


# ---- 静态资源与 SPA 回退 ----
class SPAStaticFiles(StaticFiles):
    """静态资源优先；未命中的前端路由回退 index.html。

    注意：starlette 1.x 的 self.directory 是 str（os.fspath 后的结果），
    必须用 os.path.join 拼路径，不能直接用 / 运算符。
    /api/** 的未命中不做 SPA 回退，保持 FastAPI 标准 404 响应体。
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # path 已过 os.path.normpath，Windows 下分隔符会变成 "\\"，先归一化再判断前缀。
            normalized = path.replace("\\", "/")
            if exc.status_code == 404 and not normalized.startswith("api/"):
                index_path = Path(self.directory) / "index.html"
                if index_path.is_file():
                    return FileResponse(index_path)
            raise


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
