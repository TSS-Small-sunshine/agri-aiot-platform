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
APP_VERSION = _str("APP_VERSION", "2.0.0")

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


# ============================================================================
# V2.0 新增（docs/V2_PLAN.md 第 4 节：环境变量 21 → 25）
# ============================================================================
# 运行时配置中心持久化路径：容器内 /data 是具名卷，重启不丢。
RUNTIME_CONFIG_PATH = Path(_str("RUNTIME_CONFIG_PATH", str(DATA_DIR / "runtime_config.json")))
# 推演比对话慢，独立超时（对话仍走 OPENAI_TIMEOUT_SECONDS=20）。
REASONING_TIMEOUT_SECONDS = _float("REASONING_TIMEOUT_SECONDS", 45.0)
# 指令下发后等回执的时限，超时把 commands.status 标为 timeout。
COMMAND_ACK_TIMEOUT_SECONDS = _float("COMMAND_ACK_TIMEOUT_SECONDS", 30.0)
# 模拟器气象发布间隔。
WEATHER_INTERVAL_SECONDS = _int("WEATHER_INTERVAL_SECONDS", 30)

# ---- V2 MQTT 主题（V2_PLAN.md 第 5 节；主题名是契约的一部分，不开放为环境变量）----
MQTT_WEATHER_TOPIC = "agri/weather/+"
MQTT_COMMAND_ACK_TOPIC = "agri/command_ack/+/+"
MQTT_COMMAND_TOPIC_TEMPLATE = "agri/command/{plot_code}/{device_code}"
MQTT_COMMAND_QOS = 1

# ---- 指令动作白名单（V2_PLAN.md 第 3 节 commands.action 注释）----
COMMAND_ACTIONS = ("irrigation_on", "irrigation_off", "pesticide_dose", "ventilation_on")

# ---- 农学先验模型口径（V2_PLAN.md 第 13 节第 5 条，答辩口径，不得随手改）----
POWER_KWH_PER_MU = 0.15                  # 亩均滴灌耗电 kWh
YIELD_LOSS_MIN_PCT = 15.0                # 水分胁迫减产下限
YIELD_LOSS_MAX_PCT = 25.0                # 水分胁迫减产上限
REASONING_PRIOR_TOLERANCE_PCT = 15.0     # 大模型数字与先验偏差超过该值即以先验为准
PROMPT_MAX_BYTES = 8192                  # prompt 截断上限（第 12 节 2C2G 内存约束）
REASONING_WINDOW_MINUTES = 10            # 推演读取的"最近 N 分钟"遥测窗口
REASONING_HISTORY_LIMIT = 100            # /api/reasoning/history 条数上限
COMMAND_HISTORY_LIMIT = 100              # /api/command/history 条数上限
WEATHER_FORECAST_HOURS = 24              # 气象预报时长

# ---- 地块元数据（V2_PLAN.md 第 6 节 /api/meta 扩展：2.5D 网格坐标 + 作物/面积/物候期）----
PLOTS = [
    {
        "plot_code": "A",
        "plot_name": "A区·柑橘示范园",
        "name": "A区柑橘园",
        "crop": "柑橘(沃柑)",
        "area_mu": 12.5,
        "stage": "果实膨大期",
        "col": 0,
        "row": 0,
    },
    {
        "plot_code": "B",
        "plot_name": "B区·柑橘试验园",
        "name": "B区柑橘园",
        "crop": "柑橘(沙糖桔)",
        "area_mu": 9.8,
        "stage": "果实膨大期",
        "col": 1,
        "row": 0,
    },
]

PLOT_BY_CODE = {p["plot_code"]: p for p in PLOTS}

# ---- 作物清单（/api/meta 的 crops 段）----
CROPS = [
    {
        "crop_code": "citrus-wo",
        "name": "柑橘(沃柑)",
        "stage": "果实膨大期",
        "plot_codes": ["A"],
        "area_mu": 12.5,
    },
    {
        "crop_code": "citrus-st",
        "name": "柑橘(沙糖桔)",
        "stage": "果实膨大期",
        "plot_codes": ["B"],
        "area_mu": 9.8,
    },
]

# ---- 农资 SKU 种子（V2_PLAN.md 第 3 节：启动幂等 seed 6 条，INSERT OR IGNORE 不覆盖用户改动）----
SKUS = [
    {
        "id": "sku-water-retainer",
        "name": "抗旱保水剂",
        "category": "土壤调理",
        "price": 68.0,
        "unit": "袋(5kg)",
        "image": "sku-water-retainer",
        "stock": 120,
        "description": "高分子吸水树脂，按 1:200 吸水，树盘撒施可提升土壤持水能力 30% 以上。",
        "keywords": "抗旱,保水,保墒,干旱,缺水,土壤",
    },
    {
        "id": "sku-citrus-soluble",
        "name": "柑橘专用水溶肥",
        "category": "肥料",
        "price": 156.0,
        "unit": "袋(20kg)",
        "image": "sku-citrus-soluble",
        "stock": 80,
        "description": "高钾配方 12-6-40+TE，壮果期随水滴灌，单次浓度控制在 0.2%~0.3%。",
        "keywords": "施肥,水肥,追肥,营养,壮果,膨大,钾",
    },
    {
        "id": "sku-acaricide",
        "name": "杀螨剂",
        "category": "植保",
        "price": 42.0,
        "unit": "瓶(500ml)",
        "image": "sku-acaricide",
        "stock": 200,
        "description": "螺螨酯悬浮剂，针对红蜘蛛卵与若螨，重点喷叶背，7 天后视虫口密度补喷。",
        "keywords": "红蜘蛛,螨,虫害,植保,农药,病虫害",
    },
    {
        "id": "sku-calcium-foliar",
        "name": "叶面钙肥",
        "category": "肥料",
        "price": 38.0,
        "unit": "瓶(1L)",
        "image": "sku-calcium-foliar",
        "stock": 150,
        "description": "螯合钙叶面肥，果实膨大期喷施增强果皮韧性，降低裂果率。",
        "keywords": "裂果,补钙,叶面肥,钙,保果",
    },
    {
        "id": "sku-drip-tape",
        "name": "滴灌带",
        "category": "灌溉",
        "price": 210.0,
        "unit": "卷(1000m)",
        "image": "sku-drip-tape",
        "stock": 60,
        "description": "贴片式滴灌带，滴头间距 30cm，流量 2L/h，配合水肥一体化少量多次。",
        "keywords": "滴灌,灌溉,缺水,抗旱,墒情,水肥一体化",
    },
    {
        "id": "sku-soil-probe",
        "name": "土壤墒情探头",
        "category": "设备",
        "price": 320.0,
        "unit": "支",
        "image": "sku-soil-probe",
        "stock": 45,
        "description": "频域反射式土壤水分温度一体探头，RS485 输出，埋深 20cm/40cm 双层布点。",
        "keywords": "墒情,传感,监测,探头,土壤水分,物联网",
    },
]
