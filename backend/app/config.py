"""集中式配置：可调参数只从环境变量读取（契约第 2 节），阈值常量见契约第 6 节。"""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent          # backend/app
BACKEND_DIR = APP_DIR.parent                       # backend
REPO_ROOT = BACKEND_DIR.parent                     # 仓库根目录


def _str(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or value == "" else value


def _int(name: str, default: int) -> int:
    try:
        return int(_str(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_str(name, str(default)))
    except ValueError:
        return default


# ---- 应用 ----
APP_PORT = _int("APP_PORT", 8000)
APP_VERSION = _str("APP_VERSION", "1.0.0")

# ---- 数据 ----
# 容器内由 .env 提供 DATA_DIR=/data、DB_PATH=/data/agri.db；裸机开发回落到仓库内 data/。
DATA_DIR = Path(_str("DATA_DIR", str(REPO_ROOT / "data")))
DB_PATH = Path(_str("DB_PATH", str(DATA_DIR / "agri.db")))
# 相对 __file__ 计算，容器内即 /app/app/static，裸机即 backend/app/static。
STATIC_DIR = Path(_str("STATIC_DIR", str(APP_DIR / "static")))

# ---- MQTT ----
MQTT_HOST = _str("MQTT_HOST", "localhost")
MQTT_PORT = _int("MQTT_PORT", 1883)
MQTT_TOPIC = _str("MQTT_TOPIC", "agri/telemetry/+/+")
DEVICE_OFFLINE_SECONDS = _int("DEVICE_OFFLINE_SECONDS", 30)
TELEMETRY_RETENTION_DAYS = _int("TELEMETRY_RETENTION_DAYS", 7)
HISTORY_HOURS_MAX = _int("HISTORY_HOURS_MAX", 168)

# ---- HTTP ----
CORS_ORIGINS = _str("CORS_ORIGINS", "*")


def cors_origins() -> list:
    """CORS_ORIGINS 支持 `*` 或逗号分隔列表。"""
    raw = CORS_ORIGINS.strip()
    if raw == "*":
        return ["*"]
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---- 大模型 ----
OPENAI_BASE_URL = _str("OPENAI_BASE_URL", "").rstrip("/")
OPENAI_API_KEY = _str("OPENAI_API_KEY", "")
OPENAI_MODEL = _str("OPENAI_MODEL", "")
OPENAI_TIMEOUT_SECONDS = _float("OPENAI_TIMEOUT_SECONDS", 20.0)
OPENAI_MAX_RETRIES = _int("OPENAI_MAX_RETRIES", 1)
AI_HISTORY_LIMIT = _int("AI_HISTORY_LIMIT", 50)

# ---- 模拟器 ----
SIM_INTERVAL_SECONDS = _int("SIM_INTERVAL_SECONDS", 5)
SIM_DEVICES = _str(
    "SIM_DEVICES",
    "FJ-CITRUS-A01,FJ-CITRUS-A02,FJ-CITRUS-B01,FJ-CITRUS-B02",
)

# ---- 设备清单（契约第 3 节；后端种子数据与模拟器必须一致）----
DEVICES = [
    {
        "device_code": "FJ-CITRUS-A01",
        "name": "A区柑橘园环境站",
        "plot_code": "A",
        "plot_name": "A区·柑橘示范园",
        "type": "env",
        "location": "福建省南平市·A区",
    },
    {
        "device_code": "FJ-CITRUS-A02",
        "name": "A区柑橘园墒情站",
        "plot_code": "A",
        "plot_name": "A区·柑橘示范园",
        "type": "soil",
        "location": "福建省南平市·A区",
    },
    {
        "device_code": "FJ-CITRUS-B01",
        "name": "B区柑橘园环境站",
        "plot_code": "B",
        "plot_name": "B区·柑橘试验园",
        "type": "env",
        "location": "福建省南平市·B区",
    },
    {
        "device_code": "FJ-CITRUS-B02",
        "name": "B区柑橘园墒情站",
        "plot_code": "B",
        "plot_name": "B区·柑橘试验园",
        "type": "soil",
        "location": "福建省南平市·B区",
    },
]

# ---- 告警阈值（契约第 6 节 v1.1，逐条照抄）----
# temperature：正常 15~35℃；>38 或 <5 → critical；35~38 或 5~15 → warning
# humidity   ：正常 40~85%；<40 或 >85 → warning；<30 或 >95 → critical（对称双档，无静默带）
# soil_moisture：正常 35~80%；<35 → warning；<25 → critical
THRESHOLDS = {
    "temperature": {"min": 15.0, "max": 35.0, "critical_min": 5.0, "critical_max": 38.0},
    "humidity": {"min": 40.0, "max": 85.0, "critical_min": 30.0, "critical_max": 95.0},
    "soil_moisture": {"min": 35.0, "max": 80.0, "critical_min": 25.0},
}


def meta_thresholds() -> dict:
    """GET /api/meta 暴露的阈值结构（字段与契约示例逐字段一致）。"""
    return {
        "temperature": {
            "min": 15,
            "max": 35,
            "critical_min": 5,
            "critical_max": 38,
        },
        "humidity": {
            "min": 40,
            "max": 85,
            "critical_min": 30,
            "critical_max": 95,
        },
        "soil_moisture": {"min": 35, "max": 80, "critical_min": 25},
    }
