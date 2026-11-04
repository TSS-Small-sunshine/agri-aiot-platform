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
    "FJ-CITRUS-A01,FJ-CITRUS-A02,FJ-CITRUS-B01,FJ-CITRUS-B02,FJ-MUSH-C01",
)
# V2.1 C-1：滴灌真实速率（%/秒，28.8 点/小时，滴灌量级）。knowledge.py 的灌溉时长
# 由本速率反推，两侧必须共用同一个值才自洽。
SIM_IRRIGATION_RATE_PCT_PER_S = _float("SIM_IRRIGATION_RATE_PCT_PER_S", 0.008)
# V2.1 C-1：显式演示加速倍率（压缩的是时钟，不是物理量）。1 = 完全真实。
SIM_DEMO_ACCELERATION = _float("SIM_DEMO_ACCELERATION", 30.0)
# V2.1 C-5：默认 0 = 不注入脏值（旧默认 0.12 会污染 summary 的 min/max）。
SIM_BAD_PROBABILITY = _float("SIM_BAD_PROBABILITY", 0.0)
# V2.1 C-5：演示场景 normal|drought|heat|disease|cold（连续过程，非单点）。
SIM_SCENARIO = _str("SIM_SCENARIO", "normal").strip().lower() or "normal"
# V2.1 C-10：按概率整条丢弃遥测，演示"数据缺失"。0 = 关闭（默认），建议演示值 0.05~0.2。
SIM_PACKET_LOSS = _float("SIM_PACKET_LOSS", 0.0)

# ---- 设备清单（契约第 3 节；后端种子数据与模拟器必须一致）----
DEVICES = [
    {
        "device_code": "FJ-CITRUS-A01",
        "name": "A区柑橘园环境站",
        "plot_code": "A",
        "plot_name": "A区·柑橘示范园",
        "type": "env",
        "location": "福建省南平市·A区",
        "install_note": "冠层 1.5m",
    },
    {
        "device_code": "FJ-CITRUS-A02",
        "name": "A区柑橘园墒情站",
        "plot_code": "A",
        "plot_name": "A区·柑橘示范园",
        "type": "soil",
        "location": "福建省南平市·A区",
        "install_note": "20cm 埋深",
    },
    {
        "device_code": "FJ-CITRUS-B01",
        "name": "B区柑橘园环境站",
        "plot_code": "B",
        "plot_name": "B区·柑橘试验园",
        "type": "env",
        "location": "福建省南平市·B区",
        "install_note": "冠层 1.5m",
    },
    {
        "device_code": "FJ-CITRUS-B02",
        "name": "B区柑橘园墒情站",
        "plot_code": "B",
        "plot_name": "B区·柑橘试验园",
        "type": "soil",
        "location": "福建省南平市·B区",
        "install_note": "20cm 埋深",
    },
    {
        "device_code": "FJ-MUSH-C01",
        "name": "C区温室环境站",
        "plot_code": "C",
        "plot_name": "C区·闽宁协作温室菇棚",
        "type": "env",
        "location": "宁夏银川市西夏区·闽宁镇·C区",
        "install_note": "棚内中层 1.5m",
    },
]

# 设备类型 → 指标绑定（V2.1 C-8）：同一地块两类设备各报各的指标，绝不混算。
DEVICE_METRICS = {
    "env": ("temperature", "humidity"),
    "soil": ("soil_moisture", "soil_temp"),
}
# 温室环境站额外上报 CO2（V2.1 C-10）。
GREENHOUSE_EXTRA_METRICS = ("co2",)

# ---- 告警阈值（契约第 6 节 v1.1 + V2.1 C-4，逐条照抄）----
# temperature：正常 15~35℃；>38 或 <5 → critical；35~38 或 5~15 → warning
# humidity   ：正常 40~92%；92~97 或 <40 → warning；>97 或 <30 → critical（对称双档，无静默带）
#              上限放宽到 92 是因为福建柑橘产区夜间湿度 85~95% 属常态，
#              旧上限 85 会每天刷一批无意义告警（ClawsGo 审计 C-4）。
# soil_moisture：正常 35~80%；<35 → warning；<25 → critical
# V2.1 C-12：下限从 15℃ 下修到 5℃（柑橘低温胁迫阈值），0℃ 以下才是冻害 critical。
THRESHOLDS = {
    "temperature": {"min": 5.0, "max": 35.0, "critical_min": 0.0, "critical_max": 38.0},
    "humidity": {"min": 40.0, "max": 92.0, "critical_min": 30.0, "critical_max": 97.0},
    "soil_moisture": {"min": 35.0, "max": 80.0, "critical_min": 25.0},
}

# V2.1 C-11：墒情阈值按土壤质地分档（砂壤持水差、黏壤持水好，用同一把尺子不合理）。
SOIL_TEXTURE_THRESHOLDS = {
    "砂壤": {"min": 28.0, "max": 80.0, "critical_min": 20.0},
    "壤土": {"min": 35.0, "max": 80.0, "critical_min": 25.0},
    "黏壤": {"min": 40.0, "max": 80.0, "critical_min": 30.0},
}
DEFAULT_SOIL_TEXTURE = "壤土"

# V2.1 C-10：温室菇棚 CO₂ 阈值（ppm）。香菇出菇期需氧，CO₂ 过高抑制原基分化。
CO2_THRESHOLDS = {"min": 400.0, "max": 1200.0, "critical_min": 300.0, "critical_max": 1500.0}

# V2.1 C-12：湿度告警升级为"连续 ≥6 小时且气温在 20~28℃"才判病害风险。
# 单点/短时高湿（夜间结露、雨后）在福建产区是常态，按点判定必然刷屏；
# 而病害（炭疽/溃疡）需要"适温 + 长时高湿"两个条件同时成立。
HUMIDITY_RISK_MIN_HOURS = 6.0
HUMIDITY_RISK_TEMP_MIN = 20.0
HUMIDITY_RISK_TEMP_MAX = 28.0
# 回溯窗口：判定"连续高湿"时最多往回看多久的遥测（有界查询，避免全表扫描）。
HUMIDITY_RISK_WINDOW_HOURS = 24.0


def soil_thresholds_for(plot: dict | None) -> dict:
    """该地块实际生效的墒情阈值（按 soil_texture 分档，缺省壤土）。"""
    texture = (plot or {}).get("soil_texture") or DEFAULT_SOIL_TEXTURE
    entry = SOIL_TEXTURE_THRESHOLDS.get(texture) or SOIL_TEXTURE_THRESHOLDS[DEFAULT_SOIL_TEXTURE]
    return {"min": entry["min"], "max": entry["max"], "critical_min": entry["critical_min"]}


def meta_thresholds(plot: dict | None = None) -> dict:
    """GET /api/meta 暴露的阈值结构（字段与契约示例逐字段一致）。

    传入地块时 soil_moisture 段返回该地块按土壤质地实际生效的阈值（V2.1 C-11）。
    """
    soil = soil_thresholds_for(plot)
    return {
        "temperature": {
            "min": 5,
            "max": 35,
            "critical_min": 0,
            "critical_max": 38,
        },
        "humidity": {
            "min": 40,
            "max": 92,
            "critical_min": 30,
            "critical_max": 97,
        },
        "soil_moisture": {
            "min": int(soil["min"]),
            "max": int(soil["max"]),
            "critical_min": int(soil["critical_min"]),
        },
        # V2.1 C-10：温室 CO₂ 段（前端 Co2Card 优先用后端值，缺失才用内置兜底）。
        "co2": {
            "min": int(CO2_THRESHOLDS["min"]),
            "max": int(CO2_THRESHOLDS["max"]),
            "critical_min": int(CO2_THRESHOLDS["critical_min"]),
            "critical_max": int(CO2_THRESHOLDS["critical_max"]),
        },
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
# V2.1 C-6：耗电口径改为「每立方米灌溉水的耗电」，低扬程滴灌合理区间 0.12~0.18。
KWH_PER_M3 = 0.15                        # 灌溉耗电 kWh/m³
# V2.1 C-6：单次灌溉时长上限（24h）。超过按上限执行，方案里说明本次只覆盖亏缺的一部分。
IRRIGATION_MAX_MINUTES = 1440
# V2.1 C-11：减产率连续化后不再有 15% 下限，只保留上限（水分胁迫最大减产）。
YIELD_LOSS_MAX_PCT = 25.0                # 水分胁迫减产上限
REASONING_PRIOR_TOLERANCE_PCT = 15.0     # 大模型数字与先验偏差超过该值即以先验为准
PROMPT_MAX_BYTES = 8192                  # prompt 截断上限（第 12 节 2C2G 内存约束）
REASONING_WINDOW_MINUTES = 10            # 推演读取的"最近 N 分钟"遥测窗口
REASONING_HISTORY_LIMIT = 100            # /api/reasoning/history 条数上限
COMMAND_HISTORY_LIMIT = 100              # /api/command/history 条数上限
WEATHER_FORECAST_HOURS = 24              # 气象预报时长

# ---- 地块元数据（V2_PLAN.md 第 6 节 /api/meta 扩展：2.5D 网格坐标 + 作物/面积/物候期）----
# V2.1 C-6/C-7：地块补齐"灌溉水量平衡"所需参数与物候窗口；作物品种按产地据实（福建南平
# 主栽芦柑/南丰蜜桔，旧沃柑/沙糖桔与产地不符）；新增闽宁协作 C 区温室菇棚。
#   root_depth_cm   根层深度（cm）
#   soil_texture    土壤质地（砂壤|壤土|黏壤），决定墒情阈值
#   wetted_ratio    滴灌湿润区占根层面积比例
#   drip_emitter_lph/drip_spacing_m/row_spacing_m  滴灌系统参数（算系统流量）
#   scenario        open_field（露天）| greenhouse（温室）
#   stage_window    当前物候期的日期窗口（MM-DD，跨年时 start > end）
PLOTS = [
    {
        "plot_code": "A",
        "plot_name": "A区·柑橘示范园",
        "name": "A区柑橘园",
        "crop": "柑橘(芦柑)",
        "area_mu": 12.5,
        "stage": "果实转色期",
        "col": 0,
        "row": 0,
        "root_depth_cm": 40.0,
        "soil_texture": "壤土",
        "wetted_ratio": 0.30,
        "drip_emitter_lph": 2.0,
        "drip_spacing_m": 0.30,
        "row_spacing_m": 4.0,
        "scenario": "open_field",
        "stage_window": {"start": "10-01", "end": "11-30"},
        "stage_cycle": [
            {"stage": "休眠期", "start": "01-01", "end": "02-28"},
            {"stage": "春梢现蕾期", "start": "03-01", "end": "04-30"},
            {"stage": "谢花坐果期", "start": "05-01", "end": "06-30"},
            {"stage": "果实膨大期", "start": "07-01", "end": "09-30"},
            {"stage": "果实转色期", "start": "10-01", "end": "11-30"},
            {"stage": "成熟采收期", "start": "12-01", "end": "12-31"},
        ],
    },
    {
        "plot_code": "B",
        "plot_name": "B区·柑橘试验园",
        "name": "B区柑橘园",
        "crop": "柑橘(南丰蜜桔)",
        "area_mu": 9.8,
        "stage": "成熟采收期",
        "col": 1,
        "row": 0,
        "root_depth_cm": 40.0,
        "soil_texture": "砂壤",
        "wetted_ratio": 0.30,
        "drip_emitter_lph": 2.0,
        "drip_spacing_m": 0.30,
        "row_spacing_m": 4.0,
        "scenario": "open_field",
        "stage_window": {"start": "11-01", "end": "12-31"},
        "stage_cycle": [
            {"stage": "休眠期", "start": "01-01", "end": "02-28"},
            {"stage": "春梢现蕾期", "start": "03-01", "end": "04-30"},
            {"stage": "谢花坐果期", "start": "05-01", "end": "06-30"},
            {"stage": "果实膨大期", "start": "07-01", "end": "09-30"},
            {"stage": "果实转色期", "start": "10-01", "end": "10-31"},
            {"stage": "成熟采收期", "start": "11-01", "end": "12-31"},
        ],
    },
    {
        "plot_code": "C",
        "plot_name": "C区·闽宁协作温室菇棚",
        "name": "C区菇棚",
        "crop": "香菇",
        "area_mu": 1.2,
        "stage": "出菇期",
        "col": 2,
        "row": 0,
        "root_depth_cm": 15.0,
        "soil_texture": "壤土",
        "wetted_ratio": 0.25,
        "drip_emitter_lph": 2.0,
        "drip_spacing_m": 0.30,
        "row_spacing_m": 0.40,
        "scenario": "greenhouse",
        "stage_window": {"start": "09-01", "end": "04-30"},
        "stage_cycle": [
            {"stage": "菌丝培养期", "start": "05-01", "end": "08-31"},
            {"stage": "出菇期", "start": "09-01", "end": "04-30"},
        ],
    },
]

PLOT_BY_CODE = {p["plot_code"]: p for p in PLOTS}

DEVICE_BY_CODE = {d["device_code"]: d for d in DEVICES}


def _in_stage_window(month_day: str, start: str, end: str) -> bool:
    if start <= end:
        return start <= month_day <= end
    return month_day >= start or month_day <= end


def resolve_stage(plot: dict | None, now=None) -> str:
    """按当前月份推导物候期（V2.1 C-7），不再写死。

    优先走地块的 stage_cycle（全年窗口表）；只有 stage_window 时按该窗口判断，
    命中返回声明值，未命中返回「非该物候期」。
    """
    if not plot:
        return ""
    if now is None:
        from datetime import datetime as _dt

        now = _dt.now()
    month_day = now.strftime("%m-%d")
    cycle = plot.get("stage_cycle") or []
    for entry in cycle:
        start, end = entry.get("start"), entry.get("end")
        if start and end and _in_stage_window(month_day, start, end):
            return entry.get("stage", "")
    window = plot.get("stage_window") or {}
    start, end = window.get("start"), window.get("end")
    if start and end and _in_stage_window(month_day, start, end):
        return plot.get("stage", "")
    return plot.get("stage", "")


def plot_meta(plot_code: str) -> dict | None:
    """地块元数据（stage 按当前月份推导）；未知地块返回 None。"""
    plot = PLOT_BY_CODE.get(plot_code)
    if plot is None:
        return None
    resolved = dict(plot)
    resolved["stage"] = resolve_stage(plot)
    return resolved

# ---- 作物清单（/api/meta 的 crops 段）----
CROPS = [
    {
        "crop_code": "citrus-lugan",
        "name": "柑橘(芦柑)",
        "stage": "果实转色期",
        "plot_codes": ["A"],
        "area_mu": 12.5,
    },
    {
        "crop_code": "citrus-nanfeng",
        "name": "柑橘(南丰蜜桔)",
        "stage": "成熟采收期",
        "plot_codes": ["B"],
        "area_mu": 9.8,
    },
    {
        "crop_code": "shiitake",
        "name": "香菇",
        "stage": "出菇期",
        "plot_codes": ["C"],
        "area_mu": 1.2,
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
        "id": "sku-fungicide",
        "name": "保护性杀菌剂(代森锰锌)",
        "category": "植保",
        "price": 56.0,
        "unit": "袋(500g)",
        "image": "sku-fungicide",
        "stock": 100,
        "description": "80% 代森锰锌可湿性粉剂，炭疽病/溃疡病保护性预防用药，发病前或雨前喷施；具体稀释倍数与安全间隔期按标签与农技员确认。",
        "keywords": "炭疽病,溃疡病,杀菌剂,代森锰锌,咪鲜胺,病害,预防,高湿",
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
