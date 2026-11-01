"""MQTT 接入：后台线程订阅遥测主题，落库 + 更新 last_seen + 触发阈值判定。

关键约束（来自任务书）：
- 在 lifespan 内后台启动，断线自动重连。
- Broker 连不上**不得**让整个服务起不来：一律降级为 connected=False，
  /api/health 如实报告，HTTP 接口照常可用。
"""
from __future__ import annotations

import json
import logging
import threading

import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion

from . import alerts, config, db
from .timeutil import normalize_iso

log = logging.getLogger("agri.mqtt")

METRIC_KEYS = ("temperature", "humidity", "soil_moisture", "soil_temp", "battery")


class MqttIngest:
    """遥测接入器。任何网络异常都被吞掉并记录，绝不冒泡到 HTTP 层。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._client: mqtt.Client | None = None
        self._connected = False
        self._last_error: str | None = None
        self._messages = 0
        self._alerts = 0
        self._started = False

    # ---- 状态 ----
    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    def stats(self) -> dict:
        with self._lock:
            return {
                "connected": self._connected,
                "last_error": self._last_error,
                "messages": self._messages,
                "alerts": self._alerts,
            }

    def _set(self, **kwargs) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self, f"_{key}", value)

    # ---- paho 回调 ----
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", reason_code != 0):
            self._set(connected=False, last_error=f"连接被拒绝：{reason_code}")
            log.warning("MQTT 连接被拒绝: %s", reason_code)
            return
        self._set(connected=True, last_error=None)
        client.subscribe(config.MQTT_TOPIC, qos=0)
        log.info("MQTT 已连接 %s:%s，订阅 %s", config.MQTT_HOST, config.MQTT_PORT, config.MQTT_TOPIC)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self._set(connected=False, last_error=f"连接断开：{reason_code}")
        log.warning("MQTT 断开（将自动重连）: %s", reason_code)

    def _on_message(self, client, userdata, message):
        try:
            self._handle(message)
        except Exception as exc:  # noqa: BLE001 —— 单条脏消息不能中断订阅
            log.exception("处理 MQTT 消息失败: %s", exc)

    # ---- 业务 ----
    def _handle(self, message) -> None:
        topic = getattr(message, "topic", "")
        parts = topic.split("/")
        # agri/telemetry/{plot_code}/{device_code}
        topic_plot = parts[2] if len(parts) >= 4 else None
        topic_device = parts[3] if len(parts) >= 4 else None

        try:
            payload = json.loads(message.payload.decode("utf-8", errors="replace"))
        except (ValueError, AttributeError):
            log.warning("丢弃非法 JSON payload，topic=%s", topic)
            return
        if not isinstance(payload, dict):
            log.warning("丢弃非对象 payload，topic=%s", topic)
            return

        device_code = str(payload.get("device_code") or topic_device or "").strip()
        if not device_code:
            log.warning("丢弃缺少 device_code 的消息，topic=%s", topic)
            return

        plot_code = str(payload.get("plot_code") or topic_plot or "?").strip()
        ts = normalize_iso(payload.get("ts"))
        metrics = {key: payload.get(key) for key in METRIC_KEYS if payload.get(key) is not None}

        self._ensure_device(device_code, plot_code, payload.get("type"))
        db.insert_telemetry(device_code, ts, metrics, json.dumps(payload, ensure_ascii=False))
        db.touch_device(device_code, ts)

        fired = alerts.evaluate(device_code, metrics)
        with self._lock:
            self._messages += 1
            self._alerts += len(fired)

    def _ensure_device(self, device_code: str, plot_code: str, dev_type) -> None:
        """未知设备自动登记，保证数据不丢（契约设备清单以外的设备也能接入）。"""
        known = {d["device_code"]: d for d in config.DEVICES}
        if device_code in known:
            return
        row = db.query_one("SELECT device_code FROM devices WHERE device_code = ?", (device_code,))
        if row:
            return
        from .timeutil import now_iso
        db.execute(
            """INSERT OR IGNORE INTO devices
               (device_code, name, plot_code, plot_name, type, location, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'online', ?)""",
            (
                device_code, device_code, plot_code, f"{plot_code}区",
                str(dev_type or "env"), None, now_iso(),
            ),
        )

    # ---- 生命周期 ----
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        try:
            client = mqtt.Client(
                CallbackAPIVersion.VERSION2,
                client_id=f"agri-backend-{id(self)}",
                protocol=mqtt.MQTTv311,
            )
            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message
            client.reconnect_delay_set(min_delay=1, max_delay=30)
            self._client = client
            # connect_async + loop_start：Broker 不在也能立刻返回，
            # paho 会在后台按 reconnect_delay 持续重试。
            client.connect_async(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
            client.loop_start()
            log.info("MQTT 后台线程已启动，目标 %s:%s", config.MQTT_HOST, config.MQTT_PORT)
        except Exception as exc:  # noqa: BLE001 —— 起不来也不能拖垮服务
            self._set(connected=False, last_error=f"MQTT 启动失败：{type(exc).__name__}: {exc}")
            log.exception("MQTT 启动失败，服务降级为 disconnected")

    def stop(self) -> None:
        client, self._client = self._client, None
        self._started = False
        self._set(connected=False)
        if client is None:
            return
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:  # noqa: BLE001
            log.debug("MQTT 关闭时忽略异常", exc_info=True)


ingest = MqttIngest()
