"""Pydantic 模型：字段与契约第 5 节响应体逐字段一致。

响应统一走 response_model，多余字段会被 FastAPI 过滤掉 —— 契约即校验。
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


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


class MetaResponse(BaseModel):
    plots: list[MetaPlot]
    thresholds: MetaThresholds
    sim_interval_seconds: int
