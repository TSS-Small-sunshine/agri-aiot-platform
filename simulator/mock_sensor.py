"""MQTT 传感器模拟器：遥测上行 + 气象上行 + 指令下行订阅并**真的改变行为** + 回执。

数据形态（"像真的"）：
- 温度 / 湿度 / 土壤温度 / 墒情 = 日周期正弦 + 随机噪声；
- 墒情另叠加"灌溉脉冲"（缓慢下降、偶发回升）；
- 按 SIM_BAD_PROBABILITY 概率制造越界值，用于触发并演示告警链路；
- 电池电压缓慢单调下降。

V2 新增（V2_PLAN.md 第 5/9 节）：
- 每 WEATHER_INTERVAL_SECONDS 向 agri/weather/{plot_code} 发布一条气象；
- 订阅 agri/command/{plot}/{device}（QoS 1），irrigation_on / irrigation_off /
  pesticide_dose / ventilation_on 会**真实改变后续采样数值**（见 apply_command）；
- 执行后向 agri/command_ack/{plot}/{device} 回执（QoS 1）。

断线自动重连；Broker 不可达时只打印重连提示，绝不退出。
仅依赖 paho-mqtt + 标准库。
"""
from __future__ import annotations

import json
import math
import os
import random
import signal
import sys
import time
from datetime import datetime, timedelta

import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion

try:  # 包方式导入（python -m simulator.mock_sensor）
    from . import weather as weather_mod
except ImportError:  # 脚本方式导入（python simulator/mock_sensor.py）
    import weather as weather_mod

# ---------------- 配置（全部走环境变量） ----------------
MQTT_HOST = os.getenv("MQTT_HOST") or "localhost"
MQTT_PORT = int(os.getenv("MQTT_PORT") or 1883)
SIM_INTERVAL_SECONDS = float(os.getenv("SIM_INTERVAL_SECONDS") or 5)
SIM_BAD_PROBABILITY = float(os.getenv("SIM_BAD_PROBABILITY") or 0.12)
SIM_DEVICES_RAW = os.getenv("SIM_DEVICES") or "FJ-CITRUS-A01,FJ-CITRUS-A02,FJ-CITRUS-B01,FJ-CITRUS-B02"
TOPIC_TEMPLATE = os.getenv("MQTT_TOPIC_TEMPLATE") or "agri/telemetry/{plot_code}/{device_code}"
# V2：气象发布间隔与下行指令主题（与后端 config.py 同源）
WEATHER_INTERVAL_SECONDS = float(os.getenv("WEATHER_INTERVAL_SECONDS") or 30)
WEATHER_TOPIC_TEMPLATE = os.getenv("MQTT_WEATHER_TOPIC_TEMPLATE") or "agri/weather/{plot_code}"
COMMAND_TOPIC = os.getenv("MQTT_COMMAND_TOPIC") or "agri/command/+/+"
COMMAND_ACK_TEMPLATE = os.getenv("MQTT_COMMAND_ACK_TOPIC_TEMPLATE") or "agri/command_ack/{plot_code}/{device_code}"
COMMAND_ACK_QOS = int(os.getenv("MQTT_COMMAND_QOS") or 1)
WEATHER_ENABLED = (os.getenv("SIM_WEATHER_ENABLED") or "1").strip() not in ("0", "false", "False")

# 设备清单（契约第 3 节，与后端种子数据一致）
DEVICE_CATALOG = {
    "FJ-CITRUS-A01": {"name": "A区柑橘园环境站", "plot_code": "A", "type": "env"},
    "FJ-CITRUS-A02": {"name": "A区柑橘园墒情站", "plot_code": "A", "type": "soil"},
    "FJ-CITRUS-B01": {"name": "B区柑橘园环境站", "plot_code": "B", "type": "env"},
    "FJ-CITRUS-B02": {"name": "B区柑橘园墒情站", "plot_code": "B", "type": "soil"},
}

# 每台设备的基线，制造地块间差异
BASELINE = {
    "FJ-CITRUS-A01": {"temperature": 25.5, "humidity": 70.0, "soil_moisture": 58.0, "soil_temp": 23.0, "battery": 94.0},
    "FJ-CITRUS-A02": {"temperature": 25.0, "humidity": 68.0, "soil_moisture": 52.0, "soil_temp": 22.5, "battery": 91.0},
    "FJ-CITRUS-B01": {"temperature": 26.5, "humidity": 66.0, "soil_moisture": 61.0, "soil_temp": 24.0, "battery": 88.0},
    "FJ-CITRUS-B02": {"temperature": 26.0, "humidity": 64.0, "soil_moisture": 47.0, "soil_temp": 23.5, "battery": 85.0},
}

# 越界注入的候选：与契约第 6 节 v1.1 阈值对齐，保证一定能触发告警。
# humidity 同时给 warning（36/89）与 critical（22/28.5/96/98.4）两档，
# 否则对称双档下只能演示到 critical。
OUT_OF_RANGE = {
    "temperature": [3.5, 4.8, 36.5, 38.5, 40.2],
    "humidity": [22.0, 28.5, 36.0, 89.0, 96.0, 98.4],
    "soil_moisture": [18.0, 22.5, 27.0, 30.5, 82.0, 86.5],
}

# 指令可改变行为的时长上限（分钟），防止异常 params 让设备长期跑偏
MAX_EFFECT_MINUTES = 180.0


def local_now() -> datetime:
    return datetime.now().astimezone()


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _minutes(params: dict, key: str, default: float) -> float:
    try:
        value = float(params.get(key))
    except (TypeError, ValueError):
        return default
    return max(1.0, min(MAX_EFFECT_MINUTES, value))


class DeviceState:
    """单台设备的连续状态，保证相邻采样平滑变化而不是白噪声。"""

    def __init__(self, device_code: str):
        self.device_code = device_code
        base = BASELINE.get(device_code, BASELINE["FJ-CITRUS-A01"])
        self.plot_code = DEVICE_CATALOG.get(device_code, {}).get("plot_code", "A")
        self.type = DEVICE_CATALOG.get(device_code, {}).get("type", "env")
        self.base = dict(base)
        self.phase = random.uniform(0, 2 * math.pi)
        self.drift = 0.0
        self.battery = base["battery"]
        # 灌溉状态：上次灌溉时间与灌溉剩余量
        self.irrigation_until = 0.0
        self.irrigation_rate = 0.0
        # V2：指令造成的持续扰动窗口
        self.pesticide_until = 0.0
        self.ventilation_until = 0.0
        self.last_command: dict | None = None

    # ---- 物理量生成 ----
    def _daily(self, amplitude: float, peak_hour: float = 14.0) -> float:
        """日周期正弦：峰值出现在 peak_hour 左右。"""
        now = local_now()
        hour = now.hour + now.minute / 60.0 + now.second / 3600.0
        angle = 2 * math.pi * (hour - peak_hour) / 24.0
        return amplitude * math.cos(angle)

    def _soil_moisture(self, elapsed: float) -> float:
        now_ts = time.time()
        # 土壤持续失水（蒸散）
        self.drift -= 0.010 * elapsed
        # 低于 -6.0 时自动触发一次灌溉脉冲（本地自主行为，与下行指令无关）
        if self.drift < -6.0 and now_ts > self.irrigation_until:
            self.irrigation_until = now_ts + random.uniform(20, 40)
            self.irrigation_rate = random.uniform(0.22, 0.42)
        if now_ts < self.irrigation_until:
            self.drift += self.irrigation_rate * elapsed
        else:
            self.irrigation_rate = 0.0
        self.drift = max(-16.0, min(20.0, self.drift))
        noise = random.gauss(0, 0.35)
        return self.base["soil_moisture"] + self.drift + noise

    def sample(self, elapsed: float) -> dict:
        bad = random.random() < SIM_BAD_PROBABILITY
        bad_metric = random.choice(list(OUT_OF_RANGE)) if bad else None

        temperature = self.base["temperature"] + self._daily(5.2) + random.gauss(0, 0.35)
        humidity = self.base["humidity"] - self._daily(9.0) + random.gauss(0, 1.1)
        soil_moisture = self._soil_moisture(elapsed)
        soil_temp = self.base["soil_temp"] + self._daily(2.4, peak_hour=16.0) + random.gauss(0, 0.2)

        # V2：下行指令造成的可观测扰动
        now_ts = time.time()
        if now_ts < self.ventilation_until:
            temperature -= 1.8
            humidity -= 6.0
        if now_ts < self.pesticide_until:
            soil_temp -= 1.5
            humidity += 4.0

        self.battery = max(5.0, self.battery - random.uniform(0.0008, 0.004) * max(elapsed, 1.0))

        metrics = {
            "temperature": round(temperature, 1),
            "humidity": round(max(5.0, min(100.0, humidity)), 1),
            "soil_moisture": round(max(2.0, min(100.0, soil_moisture)), 1),
            "soil_temp": round(soil_temp, 1),
            "battery": round(self.battery, 1),
        }

        # 注入越界值：直接在合法量上叠加，确保跨过阈值
        if bad_metric:
            metrics[bad_metric] = round(random.choice(OUT_OF_RANGE[bad_metric]), 1)

        return metrics

    # ---- V2：指令真正改变行为 ----
    def apply_command(self, action: str, params: dict) -> tuple[bool, str]:
        """执行下行指令，返回 (是否成功, 中文说明)。会真实改变后续采样。"""
        now_ts = time.time()
        params = params or {}
        if action == "irrigation_on":
            minutes = _minutes(params, "duration_min", 30.0)
            self.irrigation_until = now_ts + minutes * 60.0
            self.irrigation_rate = 0.85  # %/s，比本地自主脉冲强，采样上立即可见
            self.last_command = {"action": action, "params": params, "ts": iso(local_now())}
            return True, (
                f"灌溉已开启：墒情回升速率 {self.irrigation_rate}%/s，"
                f"持续 {minutes:.0f} 分钟（当前 drift={self.drift:.1f}）"
            )
        if action == "irrigation_off":
            self.irrigation_until = 0.0
            self.irrigation_rate = 0.0
            self.last_command = {"action": action, "params": params, "ts": iso(local_now())}
            return True, f"灌溉已关闭：停止补水（当前 drift={self.drift:.1f}）"
        if action == "pesticide_dose":
            dose = params.get("dose_ml", params.get("dose", 60))
            minutes = _minutes(params, "duration_min", 45.0)
            self.pesticide_until = now_ts + minutes * 60.0
            self.last_command = {"action": action, "params": params, "ts": iso(local_now())}
            return True, (
                f"已记录一次施药：剂量 {dose}ml，后续 {minutes:.0f} 分钟内"
                f" 土壤温度 -1.5℃、湿度 +4%（可观测扰动）"
            )
        if action == "ventilation_on":
            minutes = _minutes(params, "duration_min", 20.0)
            self.ventilation_until = now_ts + minutes * 60.0
            self.last_command = {"action": action, "params": params, "ts": iso(local_now())}
            return True, (
                f"通风已开启：后续 {minutes:.0f} 分钟内 气温 -1.8℃、湿度 -6%（可观测扰动）"
            )
        return False, f"未知动作 {action}，模拟器未改变行为"

    def payload(self, elapsed: float) -> str:
        ts = iso(local_now())
        body = {
            "device_code": self.device_code,
            "plot_code": self.plot_code,
            "type": self.type,
            "ts": ts,
        }
        body.update(self.sample(elapsed))
        return json.dumps(body, ensure_ascii=False)

    def topic(self) -> str:
        return TOPIC_TEMPLATE.format(plot_code=self.plot_code, device_code=self.device_code)


# ---------------- MQTT 客户端 ----------------
_running = True
_states: dict[str, DeviceState] = {}


def _handle_signal(signum, frame):  # noqa: ARG001
    global _running
    _running = False
    print(f"[simulator] 收到信号 {signum}，准备退出", flush=True)


def _on_command(client, message) -> None:
    """收到下行指令：改变行为 + 回执。"""
    topic = getattr(message, "topic", "")
    parts = topic.split("/")
    plot_code = parts[2] if len(parts) >= 4 else "?"
    device_code = parts[3] if len(parts) >= 4 else "?"
    try:
        payload = json.loads(message.payload.decode("utf-8", errors="replace"))
    except (ValueError, AttributeError):
        print(f"[simulator] 丢弃非法指令 payload，topic={topic}", flush=True)
        return
    if not isinstance(payload, dict):
        print(f"[simulator] 丢弃非对象指令 payload，topic={topic}", flush=True)
        return

    command_id = str(payload.get("command_id") or "")
    action = str(payload.get("action") or "")
    params = payload.get("params") or {}
    print(
        f"[simulator] 收到指令 {command_id} action={action} plot={plot_code} "
        f"device={device_code} params={json.dumps(params, ensure_ascii=False)}",
        flush=True,
    )

    state = _states.get(device_code)
    if state is None:
        ok, detail = False, f"本模拟器未模拟设备 {device_code}"
    else:
        ok, detail = state.apply_command(action, params)
    print(f"[simulator] 指令执行结果 {command_id}: ok={ok} detail={detail}", flush=True)

    ack = {
        "command_id": command_id,
        "status": "executed" if ok else "failed",
        "detail": detail,
        "ts": iso(local_now()),
    }
    ack_topic = COMMAND_ACK_TEMPLATE.format(plot_code=plot_code, device_code=device_code)
    info = client.publish(ack_topic, json.dumps(ack, ensure_ascii=False), qos=COMMAND_ACK_QOS, retain=False)
    print(
        f"[simulator] 已回执 {command_id} status={ack['status']} topic={ack_topic} "
        f"qos={COMMAND_ACK_QOS} rc={getattr(info, 'rc', '?')}",
        flush=True,
    )


def _on_message(client, userdata, message):  # noqa: ARG001
    try:
        _on_command(client, message)
    except Exception as exc:  # noqa: BLE001 —— 单条脏指令不能中断订阅
        print(f"[simulator] 处理指令失败：{type(exc).__name__}: {exc}", flush=True)


def build_client() -> mqtt.Client:
    client = mqtt.Client(
        CallbackAPIVersion.VERSION2,
        client_id=f"agri-simulator-{random.randint(1000, 9999)}",
        protocol=mqtt.MQTTv311,
    )

    def on_connect(c, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", reason_code != 0):
            print(f"[simulator] 连接被拒绝：{reason_code}", flush=True)
            return
        print(f"[simulator] 已连接 {MQTT_HOST}:{MQTT_PORT}", flush=True)
        c.subscribe(COMMAND_TOPIC, qos=COMMAND_ACK_QOS)
        print(f"[simulator] 已订阅下行指令 {COMMAND_TOPIC} (qos={COMMAND_ACK_QOS})", flush=True)

    def on_disconnect(c, userdata, flags, reason_code, properties=None):
        print(f"[simulator] 连接断开（{reason_code}），paho 将自动重连…", flush=True)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = _on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client


def resolve_devices() -> list[str]:
    codes = [c.strip() for c in SIM_DEVICES_RAW.split(",") if c.strip()]
    if not codes:
        codes = list(DEVICE_CATALOG)
    unknown = [c for c in codes if c not in DEVICE_CATALOG]
    if unknown:
        print(f"[simulator] 提示：{unknown} 不在契约设备清单中，仍按 plot A/env 发布", flush=True)
    return codes


def main() -> int:
    global _states
    signal.signal(signal.SIGINT, _handle_signal)
    try:
        signal.signal(signal.SIGTERM, _handle_signal)
    except (AttributeError, ValueError):
        pass

    device_codes = resolve_devices()
    _states = {code: DeviceState(code) for code in device_codes}
    states = _states

    # V2：气象按地块发布（地块集合来自所选设备）
    plots = sorted({s.plot_code for s in states.values()})
    weather_states = {code: weather_mod.WeatherState(code) for code in plots}

    print(
        f"[simulator] 目标 {MQTT_HOST}:{MQTT_PORT}，间隔 {SIM_INTERVAL_SECONDS}s，"
        f"设备 {device_codes}，越界概率 {SIM_BAD_PROBABILITY}",
        flush=True,
    )
    print(
        f"[simulator] 气象发布 {'开启' if WEATHER_ENABLED else '关闭'}，间隔 {WEATHER_INTERVAL_SECONDS}s，"
        f"地块 {plots}，主题 {WEATHER_TOPIC_TEMPLATE}",
        flush=True,
    )

    client = build_client()
    # connect_async + loop_start：Broker 不可达时立刻返回并后台重连，不退出。
    try:
        client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
        client.loop_start()
    except Exception as exc:  # noqa: BLE001
        print(f"[simulator] 启动异常（仍将继续重试）：{type(exc).__name__}: {exc}", flush=True)

    last = time.time()
    last_weather = 0.0
    warned = False
    tick = 0
    try:
        while _running:
            now = time.time()
            elapsed = max(now - last, 0.001)
            last = now

            if client.is_connected():
                warned = False
                for code, state in states.items():
                    client.publish(state.topic(), state.payload(elapsed), qos=0, retain=False)
                tick += 1
                if tick % 12 == 1:
                    print(
                        f"[simulator] 已发布 {tick} 轮，最新 ts={iso(local_now())}",
                        flush=True,
                    )

                # V2：气象按自己的节奏发布（默认 30s）
                if WEATHER_ENABLED and now - last_weather >= WEATHER_INTERVAL_SECONDS:
                    last_weather = now
                    for plot_code, wstate in weather_states.items():
                        client.publish(
                            wstate.topic(), wstate.payload(max(WEATHER_INTERVAL_SECONDS, 1.0)),
                            qos=0, retain=False,
                        )
                    print(
                        f"[simulator] 已发布气象 {len(weather_states)} 条（地块 {plots}）"
                        f" ts={iso(local_now())}",
                        flush=True,
                    )
            elif not warned:
                print(
                    f"[simulator] 未连接 {MQTT_HOST}:{MQTT_PORT}，持续重连中（服务不可用不影响本进程）",
                    flush=True,
                )
                warned = True

            # 分片睡眠，保证 Ctrl+C 能及时响应
            deadline = time.time() + SIM_INTERVAL_SECONDS
            while _running and time.time() < deadline:
                time.sleep(min(0.2, deadline - time.time()))
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        print("[simulator] 已停止", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
