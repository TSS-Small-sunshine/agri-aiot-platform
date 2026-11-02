"""Pydantic 模型：字段与契约第 5 节响应体逐字段一致。

响应统一走 response_model，多余字段会被 FastAPI 过滤掉 —— 契约即校验。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from . import config


# ---------------- 通用 ----------------
class OkAck(BaseModel):
    ok: bool
    id: int


class Detail(BaseModel):
    detail: str


# ---------------- /api/health ----------------
class HealthDb(BaseModel):
    ok: bool
    path: str


class HealthMqtt(BaseModel):
    connected: bool
    host: str
    port: int
    topic: str


class HealthLlm(BaseModel):
    configured: bool
    base_url: str | None = None
    degraded: bool


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_s: float
    db: HealthDb
    mqtt: HealthMqtt
    llm: HealthLlm


# ---------------- 遥测 ----------------
class LatestTelemetry(BaseModel):
    ts: str | None = None
    temperature: float | None = None
    humidity: float | None = None
    soil_moisture: float | None = None
    soil_temp: float | None = None
    battery: float | None = None


class DeviceItem(BaseModel):
    device_code: str
    name: str
    plot_code: str
    plot_name: str | None = None
    type: str
    location: str | None = None
    status: str
    last_seen: str | None = None
    latest: LatestTelemetry | None = None


class DevicesResponse(BaseModel):
    total: int
    online: int
    offline: int
    items: list[DeviceItem]


class TelemetryLatestItem(LatestTelemetry):
    device_code: str
    plot_code: str


class TelemetryLatestResponse(BaseModel):
    items: list[TelemetryLatestItem]


class HistoryPoint(BaseModel):
    ts: str
    temperature: float | None = None
    humidity: float | None = None
    soil_moisture: float | None = None
    soil_temp: float | None = None


class TelemetryHistoryResponse(BaseModel):
    device_code: str
    hours: int | float
    count: int
    points: list[HistoryPoint]


class StatBlock(BaseModel):
    avg: float | None = None
    min: float | None = None
    max: float | None = None


class TelemetrySummaryResponse(BaseModel):
    hours: int | float
    samples: int
    temperature: StatBlock
    humidity: StatBlock
    soil_moisture: StatBlock


# ---------------- 告警 ----------------
class AlertItem(BaseModel):
    id: int
    device_code: str
    metric: str
    value: float | None = None
    threshold: float | None = None
    level: str | None = None
    message: str | None = None
    acked: int = 0
    created_at: str


class AlertsResponse(BaseModel):
    total: int
    unacked: int
    items: list[AlertItem]


# ---------------- 大模型 ----------------
class ModelItem(BaseModel):
    id: str
    label: str
    source: str


class AiModelsResponse(BaseModel):
    configured: bool
    degraded: bool
    default_model: str
    error: str | None = None
    items: list[ModelItem]


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = None
    model: str | None = None

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("question must not be blank")
        return text


class ChatResponse(BaseModel):
    answer: str
    model: str
    degraded: bool
    latency_ms: int
    session_id: str | None = None
    created_at: str
    error: str | None = None


class ChatHistoryItem(BaseModel):
    id: int
    question: str
    answer: str | None = None
    model: str | None = None
    degraded: int = 0
    latency_ms: int | None = None
    created_at: str


class ChatHistoryResponse(BaseModel):
    total: int
    items: list[ChatHistoryItem]


# ---------------- /api/meta ----------------
class MetaPlot(BaseModel):
    plot_code: str
    plot_name: str
    devices: list[str]
    # ---- V2 扩展（V1 字段逐字段保留，只增不改）----
    name: str | None = None
    crop: str | None = None
    area_mu: float | None = None
    stage: str | None = None
    col: int | None = None
    row: int | None = None


class MetaTemperature(BaseModel):
    min: int
    max: int
    critical_min: int
    critical_max: int


class MetaHumidity(BaseModel):
    min: int
    max: int
    critical_min: int
    critical_max: int


class MetaSoilMoisture(BaseModel):
    min: int
    max: int
    critical_min: int


class MetaThresholds(BaseModel):
    temperature: MetaTemperature
    humidity: MetaHumidity
    soil_moisture: MetaSoilMoisture


class MetaCrop(BaseModel):
    crop_code: str
    name: str
    stage: str | None = None
    plot_codes: list[str] = Field(default_factory=list)
    area_mu: float | None = None


class MetaWeather(BaseModel):
    interval_seconds: int
    topic: str
    items: list["WeatherPoint"] = Field(default_factory=list)


class MetaResponse(BaseModel):
    plots: list[MetaPlot]
    thresholds: MetaThresholds
    sim_interval_seconds: int
    # ---- V2 扩展 ----
    crops: list[MetaCrop] = Field(default_factory=list)
    weather: MetaWeather | None = None

# ============================================================================
# V2.0 新增模型（docs/V2_PLAN.md 第 6 节 12 条 REST）
# V1 的 11 个接口模型一律只增不改。
# ============================================================================


# ---------------- 运行时配置中心 ----------------
class ConfigResponse(BaseModel):
    base_url: str | None = None
    api_key_masked: str | None = None
    model: str | None = None
    configured: bool
    source: str
    path: str


class ConfigUpdateRequest(BaseModel):
    """api_key：键缺省=保持不变，null=清除，空串=保持不变（V2_PLAN.md 第 6 节）。"""

    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class ConfigTestResponse(BaseModel):
    ok: bool
    latency_ms: int
    models: list[str] = Field(default_factory=list)
    error: str | None = None


# ---------------- 推演（第 7 节冻结结构） ----------------
class ReasoningNodeCommand(BaseModel):
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    device_code: str | None = None


class ReasoningNodeEffect(BaseModel):
    soil_moisture_delta: float | None = None
    yield_recover_pct: float | None = None


class ReasoningNode(BaseModel):
    id: str
    type: Literal["current", "risk", "plan"]
    level: int = 0
    parent: str | None = None
    label: str
    sub: str = ""
    severity: Literal["good", "warn", "high"] = "good"
    command: ReasoningNodeCommand | None = None
    effect: ReasoningNodeEffect | None = None
    sku_keywords: list[str] = Field(default_factory=list)


class ReasoningLink(BaseModel):
    source: str
    target: str


class ReasoningTree(BaseModel):
    nodes: list[ReasoningNode]
    links: list[ReasoningLink] = Field(default_factory=list)


class WhiteboxStep(BaseModel):
    step: str
    detail: str
    ts: str | None = None


class ReasoningPayload(BaseModel):
    """大模型返回体校验（第 8.3 节内联 Schema 的服务端镜像）。"""

    summary: str
    yield_loss_pct: float
    power_kwh: float
    tree: ReasoningTree
    whitebox: list[WhiteboxStep] = Field(min_length=3)


class ReasoningSimulateRequest(BaseModel):
    plot_code: str = Field(..., min_length=1, max_length=32)
    node_id: str | None = None

    @field_validator("plot_code")
    @classmethod
    def _strip_plot(cls, v: str) -> str:
        text = (v or "").strip()
        if not text:
            raise ValueError("plot_code must not be blank")
        return text


class ReasoningContextPlot(BaseModel):
    plot_code: str
    plot_name: str | None = None
    name: str
    crop: str
    area_mu: float
    stage: str
    col: int | None = None
    row: int | None = None


class ReasoningContext(BaseModel):
    plot: ReasoningContextPlot
    metrics: dict[str, Any] = Field(default_factory=dict)
    metrics_stats: dict[str, Any] = Field(default_factory=dict)
    weather: dict[str, Any] | None = None
    thresholds: dict[str, Any] = Field(default_factory=dict)


class ReasoningPrior(BaseModel):
    yield_loss_pct: float
    power_kwh: float
    level: str | None = None
    hours_below_min: float | None = None


class ReasoningResponse(BaseModel):
    reasoning_id: str
    plot_code: str
    generated_at: str
    source: str
    model: str
    latency_ms: int
    degraded: bool
    error: str | None = None
    corrected: bool = False
    context: ReasoningContext
    tree: ReasoningTree
    summary: str
    yield_loss_pct: float
    power_kwh: float
    whitebox: list[WhiteboxStep]
    prior: ReasoningPrior | None = None


class ReasoningDetailResponse(ReasoningResponse):
    prompt: str | None = None
    raw_response: str | None = None


class ReasoningHistoryItem(BaseModel):
    reasoning_id: str
    plot_code: str
    source: str
    model: str | None = None
    latency_ms: int | None = None
    degraded: bool = False
    error: str | None = None
    created_at: str
    summary: str | None = None
    yield_loss_pct: float | None = None


class ReasoningHistoryResponse(BaseModel):
    total: int
    items: list[ReasoningHistoryItem]


# ---------------- 指令闭环 ----------------
class CommandExecuteRequest(BaseModel):
    reasoning_id: str | None = None
    plot_code: str = Field(..., min_length=1, max_length=32)
    device_code: str = Field(..., min_length=1, max_length=64)
    node_id: str | None = None
    action: str = Field(..., min_length=1, max_length=32)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("action")
    @classmethod
    def _known_action(cls, v: str) -> str:
        text = (v or "").strip()
        if text not in config.COMMAND_ACTIONS:
            raise ValueError("action must be one of " + ", ".join(config.COMMAND_ACTIONS))
        return text


class CommandExecuteResponse(BaseModel):
    command_id: str
    topic: str
    payload: dict[str, Any]
    status: str


class CommandHistoryItem(BaseModel):
    command_id: str
    reasoning_id: str | None = None
    plot_code: str
    device_code: str
    node_id: str | None = None
    action: str
    params: dict[str, Any] | None = None
    topic: str
    payload: dict[str, Any] | None = None
    status: str
    ack_at: str | None = None
    created_at: str
    detail: str | None = None


class CommandHistoryResponse(BaseModel):
    total: int
    items: list[CommandHistoryItem]


# ---------------- 气象 ----------------
class WeatherPoint(BaseModel):
    ts: str
    temperature: float | None = None
    humidity: float | None = None
    rainfall_mm: float | None = None
    wind_dir: str | None = None
    wind_level: int | None = None
    condition: str | None = None


class WeatherLatestResponse(BaseModel):
    plot_code: str
    latest: WeatherPoint | None = None
    forecast: list[WeatherPoint] = Field(default_factory=list)
    count: int = 0
    interval_seconds: int
    source: str


# ---------------- 农资商城 ----------------
class SkuItem(BaseModel):
    id: str
    name: str
    category: str | None = None
    price: float | None = None
    unit: str | None = None
    image: str | None = None
    stock: int | None = None
    description: str | None = None
    keywords: str | None = None


class SkuListResponse(BaseModel):
    total: int
    keyword: str | None = None
    items: list[SkuItem]


MetaWeather.model_rebuild()
