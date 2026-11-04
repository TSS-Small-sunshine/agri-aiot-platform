"""MQTT 传感器模拟器：遥测上行 + 气象上行 + 指令下行订阅并**真的改变行为** + 回执。

数据形态（"像真的"）：
- 温度 / 湿度 / 土壤温度 = 日周期正弦 + 随机噪声；
- 土壤墒情 = 蒸散失水（3~6 点/天，随温度升高加快、随湿度升高减慢、降雨期间归零）
  + 降雨补给 + 灌溉指令补给（V2.1 C-1/C-2）；
- 电池电压缓慢单调下降。

V2 新增（V2_PLAN.md 第 5/9 节）：
- 每 WEATHER_INTERVAL_SECONDS 向 agri/weather/{plot_code} 发布一条气象；
- 订阅 agri/command/{plot}/{device}（QoS 1），irrigation_on / irrigation_off /
  pesticide_dose / ventilation_on 会**真实改变后续采样数值**（见 apply_command）；
- 执行后向 agri/command_ack/{plot}/{device} 回执（QoS 1）。

V2.1 变更（ClawsGo 审计 P0-1/P0-2/P0-4）：
- 灌溉速率改为"真实速率 × 显式演示加速"：SIM_IRRIGATION_RATE_PCT_PER_S（默认 0.008 %/s）
  × SIM_DEMO_ACCELERATION（默认 30）→ 默认 0.24 %/s，30 秒约 +7.2 点（旧值 0.85 %/s
  会在 30 秒拉高 25.5 点，物理上不可能）；
- **删除**了"墒情低于 -6 自动灌溉脉冲"的本地自主行为：土壤补水只有两个来源——降雨与灌溉指令；
- SIM_BAD_PROBABILITY 默认改为 0（不注入）；设 >0 时仍注入单点越界，但 payload 带 injected=true；
- 新增 SIM_SCENARIO（normal/drought/heat/disease/cold），场景是连续过程而非单点。

V2.1 变更（C-10 设备形态差异化 + 数据缺失）：
- 上报字段按设备形态裁剪：环境站只报 temperature/humidity/battery（温室菇棚站再报 co2），
  墒情站只报 soil_moisture/soil_temp/battery，不再所有设备上报同一组字段；
- 日周期相位按 device_code 派生，各站峰值时刻错开，不再共用同一条正弦曲线；
- 电池衰减改为 0.02~0.06 点/小时（旧值 0.0008~0.004 点/秒 = 2.9~14.4 点/小时，一天就掉光）；
- 新增 SIM_PACKET_LOSS：按概率整条丢弃遥测，用于演示「数据缺失」（默认 0 = 关闭）。

断线自动重连；Broker 不可达时只打印重连提示，绝不退出。
仅依赖 paho-mqtt + 标准库。
"""
from __future__ import annotations

import hashlib
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


def _env_float(name: str, default: float) -> float:
    """读取浮点环境变量；未设置/空串/非法值一律回落默认值。"""
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"[simulator] 环境变量 {name}={raw!r} 不是数字，回落默认 {default}", flush=True)
        return default


# ---------------- 配置（全部走环境变量） ----------------
MQTT_HOST = os.getenv("MQTT_HOST") or "localhost"
MQTT_PORT = int(os.getenv("MQTT_PORT") or 1883)
SIM_INTERVAL_SECONDS = _env_float("SIM_INTERVAL_SECONDS", 5.0)
# V2.1 C-5：默认 0，不再默认注入单点越界（旧默认 0.12 会污染 summary 的 min/max）
SIM_BAD_PROBABILITY = _env_float("SIM_BAD_PROBABILITY", 0.0)
# V2.1 C-10：按概率整条丢弃遥测（0~1），演示「数据缺失」；默认 0 = 关闭
SIM_PACKET_LOSS = _env_float("SIM_PACKET_LOSS", 0.0)
SIM_DEVICES_RAW = os.getenv("SIM_DEVICES") or "FJ-CITRUS-A01,FJ-CITRUS-A02,FJ-CITRUS-B01,FJ-CITRUS-B02,FJ-MUSH-C01"
TOPIC_TEMPLATE = os.getenv("MQTT_TOPIC_TEMPLATE") or "agri/telemetry/{plot_code}/{device_code}"
# V2：气象发布间隔与下行指令主题（与后端 config.py 同源）
WEATHER_INTERVAL_SECONDS = _env_float("WEATHER_INTERVAL_SECONDS", 30.0)
WEATHER_TOPIC_TEMPLATE = os.getenv("MQTT_WEATHER_TOPIC_TEMPLATE") or "agri/weather/{plot_code}"
COMMAND_TOPIC = os.getenv("MQTT_COMMAND_TOPIC") or "agri/command/+/+"
COMMAND_ACK_TEMPLATE = os.getenv("MQTT_COMMAND_ACK_TOPIC_TEMPLATE") or "agri/command_ack/{plot_code}/{device_code}"
COMMAND_ACK_QOS = int(os.getenv("MQTT_COMMAND_QOS") or 1)
WEATHER_ENABLED = (os.getenv("SIM_WEATHER_ENABLED") or "1").strip() not in ("0", "false", "False")

# V2.1 C-1：灌溉速率 = 真实速率 × 演示加速（默认 0.008 %/s × 30 = 0.24 %/s）
SIM_IRRIGATION_RATE_PCT_PER_S = _env_float("SIM_IRRIGATION_RATE_PCT_PER_S", 0.008)
SIM_DEMO_ACCELERATION = _env_float("SIM_DEMO_ACCELERATION", 30.0)

# V2.1 C-5：演示场景
SCENARIO_NAMES = ("normal", "drought", "heat", "disease", "cold")
SIM_SCENARIO = (os.getenv("SIM_SCENARIO") or "normal").strip().lower()
if SIM_SCENARIO not in SCENARIO_NAMES:
    print(f"[simulator] 未知场景 {SIM_SCENARIO!r}，回落 normal（可选：{', '.join(SCENARIO_NAMES)}）", flush=True)
    SIM_SCENARIO = "normal"

# 设备清单（契约第 3 节，与后端种子数据一致）
DEVICE_CATALOG = {
    "FJ-CITRUS-A01": {"name": "A区柑橘园环境站", "plot_code": "A", "type": "env", "scenario": "open_field"},
    "FJ-CITRUS-A02": {"name": "A区柑橘园墒情站", "plot_code": "A", "type": "soil", "scenario": "open_field"},
    "FJ-CITRUS-B01": {"name": "B区柑橘园环境站", "plot_code": "B", "type": "env", "scenario": "open_field"},
    "FJ-CITRUS-B02": {"name": "B区柑橘园墒情站", "plot_code": "B", "type": "soil", "scenario": "open_field"},
    "FJ-MUSH-C01": {"name": "C区温室环境站", "plot_code": "C", "type": "env", "scenario": "greenhouse"},
}

# 每台设备的基线，制造地块间差异
BASELINE = {
    "FJ-CITRUS-A01": {"temperature": 25.5, "humidity": 70.0, "soil_moisture": 58.0, "soil_temp": 23.0, "battery": 94.0},
    "FJ-CITRUS-A02": {"temperature": 25.0, "humidity": 68.0, "soil_moisture": 52.0, "soil_temp": 22.5, "battery": 91.0},
    "FJ-CITRUS-B01": {"temperature": 26.5, "humidity": 66.0, "soil_moisture": 61.0, "soil_temp": 24.0, "battery": 88.0},
    "FJ-CITRUS-B02": {"temperature": 26.0, "humidity": 64.0, "soil_moisture": 47.0, "soil_temp": 23.5, "battery": 85.0},
    # V2.1 C-7：闽宁协作 C 区温室菇棚（香菇出菇期 18℃ / 88% / CO₂ 820ppm）
    "FJ-MUSH-C01": {"temperature": 18.5, "humidity": 88.0, "soil_moisture": 62.0, "soil_temp": 17.0, "battery": 97.0, "co2": 820.0},
}

# 越界注入的候选：与契约第 6 节 v1.1 阈值对齐，保证一定能触发告警。
# humidity 同时给 warning（36/89）与 critical（22/28.5/96/98.4）两档，
# 否则对称双档下只能演示到 critical。
OUT_OF_RANGE = {
    "temperature": [3.5, 4.8, 36.5, 38.5, 40.2],
    "humidity": [22.0, 28.5, 36.0, 89.0, 96.0, 98.4],
    "soil_moisture": [18.0, 22.5, 27.0, 30.5, 82.0, 86.5],
}

# 指令可改变行为的时长上限（分钟），防止异常 params 让设备长期跑偏。
# 取值必须 ≥ knowledge.py 的灌溉时长上限（V2.1 C-6 已提到 1440），否则后端算出的指令会被静默截断，
# 回执里"预计补水"与实际生效时长就对不上了（V2.1 复核修）。
MAX_EFFECT_MINUTES = 1440.0

# V2.1 C-2：蒸散口径 —— 日失水 3~6 点（0.125~0.25 点/小时），无雨无灌溉时适用
ET_BASE_PCT_PER_H = 0.19
ET_TEMP_COEFF = 0.04        # 每高于 25℃ 1℃ 加快 4%
ET_HUMIDITY_COEFF = 0.5     # 相对湿度每 1% 减缓 0.5%（0% RH → ×1.0，100% RH → ×0.5）
ET_RAIN_DAMPING = 0.6       # 有降雨时进一步减缓
SOIL_MOISTURE_FLOOR = 2.0
SOIL_MOISTURE_CEIL = 100.0

# V2.1 C-5：场景时长（模拟小时）与目标值
SCENARIO_HOURS = {"drought": 6.0, "heat": 6.0, "disease": 4.0, "cold": 8.0}
DROUGHT_TARGET_SOIL = 28.0
HEAT_TARGET_TEMP = 39.0
DISEASE_TARGET_HUMIDITY = 98.0
COLD_TARGET_TEMP = 3.0


def local_now() -> datetime:
    return datetime.now().astimezone()


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _minutes(params: dict, key: str, default: float) -> float:
    """取时长（分钟）并夹在 [1, MAX_EFFECT_MINUTES]，返回夹紧后的值。

    调用方据此生成回执，避免"声称的时长"与"实际生效时长"不一致。
    """
    try:
        value = float(params.get(key))
    except (TypeError, ValueError):
        return default
    return max(1.0, min(MAX_EFFECT_MINUTES, value))


def _effective_irrigation_rate() -> float:
    """生效灌溉速率（%/真实秒）= 真实速率 × 演示加速。"""
    return SIM_IRRIGATION_RATE_PCT_PER_S * SIM_DEMO_ACCELERATION


def _device_phase_hours(device_code: str) -> float:
    """V2.1 C-10：由 device_code 派生日周期相位（小时，0~24）。

    哈希取模映射到 0~360 度，再按 15 度/小时折算成小时偏移，
    使各站温度/湿度峰值时刻错开，看起来像微气候不同的独立站点。
    """
    digest = hashlib.md5(device_code.encode("utf-8")).hexdigest()
    return (int(digest[:8], 16) % 360) / 15.0


class Scenario:
    """V2.1 C-5：连续过程式演示场景（不是单点注入）。

    进度按"模拟小时"推进并除以演示加速倍率：SIM_DEMO_ACCELERATION=30 时，
    6 模拟小时 = 12 真实分钟；设为 1 则完全按真实时间推进。
    """

    def __init__(self, name: str, acceleration: float):
        self.name = name
        self.acceleration = max(acceleration, 1e-6)
        self.started = time.time()
        self.progress = 0.0
        hours = SCENARIO_HOURS.get(name, 0.0)
        self.duration_s = hours * 3600.0 / self.acceleration if hours else 0.0
        if name in SCENARIO_HOURS:
            print(
                f"[simulator] 演示场景 {name}：{hours:.0f} 模拟小时，"
                f"按 {self.acceleration:.0f} 倍加速约需 {self.duration_s / 60:.1f} 真实分钟",
                flush=True,
            )

    def tick(self, now_ts: float) -> None:
        if self.duration_s <= 0:
            self.progress = 0.0
            return
        self.progress = min(1.0, max(0.0, (now_ts - self.started) / self.duration_s))

    def soil_target(self, plot_code: str, base_soil: float) -> float | None:
        """干旱场景：A 区墒情从基线线性降到 28%。"""
        if self.name != "drought" or plot_code != "A":
            return None
        return base_soil - (base_soil - DROUGHT_TARGET_SOIL) * self.progress

    def ambient(
        self, plot_code: str, base_temp: float, base_humidity: float, hour: float
    ) -> tuple[float | None, float | None]:
        """高温 / 病害 / 低温场景的气温与湿度覆盖值。"""
        if self.name == "heat" and plot_code == "B":
            return base_temp + (HEAT_TARGET_TEMP - base_temp) * self.progress, None
        if self.name == "disease" and plot_code == "B":
            return None, 92.0 + (DISEASE_TARGET_HUMIDITY - 92.0) * self.progress
        if self.name == "cold" and plot_code == "B":
            night = 1.0 if (hour < 6.0 or hour >= 20.0) else 0.35
            return base_temp + (COLD_TARGET_TEMP - base_temp) * self.progress * night, None
        return None, None


class SoilPhysics:
    """V2.1 C-1/C-2：土壤墒情物理量（唯一入口是 step()）。

    水源只有两个：降雨（由气象状态给出 rain_mm）与灌溉指令；
    蒸散是唯一的失水项，且降雨期间归零。
    """

    def __init__(self, base: float):
        self.base = base
        self.drift = 0.0          # 相对基线的偏移（点）
        self.wet = 0.0            # 湿润层余量（点·秒），用于降雨/灌溉后先补后渗
        self.irrigating_until = 0.0
        self.irrigating_rate = 0.0
        self.last_et = 0.0
        self.acceleration = max(SIM_DEMO_ACCELERATION, 1e-6)

    def start_irrigation(self, now_ts: float, minutes: float) -> tuple[float, float]:
        """minutes 是"模拟分钟"：按演示加速折算成真实秒后开闸。

        速率取**真实速率**（%/模拟秒），于是总补水量 = SIM_IRRIGATION_RATE_PCT_PER_S
        × 60 × minutes 个百分点，与 knowledge.py 的灌溉时长口径严格自洽（V2.1 C-1/AC2）。
        """
        real_seconds = minutes * 60.0 / self.acceleration
        self.irrigating_until = now_ts + real_seconds
        self.irrigating_rate = SIM_IRRIGATION_RATE_PCT_PER_S
        return self.irrigating_rate, real_seconds

    def stop_irrigation(self) -> None:
        self.irrigating_until = 0.0
        self.irrigating_rate = 0.0

    @property
    def irrigating(self) -> bool:
        return self.irrigating_rate > 0 and time.time() < self.irrigating_until

    def step(self, elapsed: float, temperature: float, humidity: float, rain_mm: float) -> float:
        """推进一个时间步（elapsed = **模拟秒**），返回本次灌溉补水量（点）。

        蒸散与灌溉都按模拟时间推进（演示加速压缩的是时钟，不是物理量）；
        rain_mm 由调用方按真实时间从气象状态换算后传入 —— 气象模块是降雨量的唯一权威，
        避免土壤侧二次放大把 24h 累计雨量算成上限的 30 倍。
        """
        elapsed = max(float(elapsed), 0.0)
        # 1) 灌溉补给（模拟时间推进；开闸时长已在 start_irrigation 里按加速折算）
        irrigated = 0.0
        if time.time() < self.irrigating_until and self.irrigating_rate > 0:
            irrigated = self.irrigating_rate * elapsed
            self.drift += irrigated
        elif self.irrigating_rate > 0:
            self.irrigating_rate = 0.0  # 到时自动停止

        # 2) 降雨补给（先补湿润层，超出部分按 55% 入渗）
        if rain_mm > 0:
            self.wet += rain_mm * 1.5
        if self.wet > 0:
            absorbed = min(self.wet, elapsed * 0.02)
            self.wet -= absorbed
            self.drift += absorbed * 0.55

        # 3) 蒸散失水（降雨期间归零）
        et_per_h = (
            ET_BASE_PCT_PER_H
            * (1.0 + ET_TEMP_COEFF * (temperature - 25.0))
            * (1.0 - ET_HUMIDITY_COEFF * humidity / 100.0)
        )
        if rain_mm > 0:
            et_per_h *= 1.0 - ET_RAIN_DAMPING
        et_per_h = max(0.0, et_per_h)
        self.last_et = et_per_h
        self.drift -= et_per_h * elapsed / 3600.0

        self.drift = max(-60.0, min(60.0, self.drift))
        # 输出上限：墒情不允许越过 [FLOOR, CEIL]，相对偏移也一并封顶。
        # 否则灌溉会把 drift 一路推到 +60，输出虽被 DeviceState 截到 100，
        # 停止补水后却要回落很久，看起来像"关闸了还在涨"（V2.1 复核修）。
        self.drift = max(SOIL_MOISTURE_FLOOR - self.base,
                         min(SOIL_MOISTURE_CEIL - self.base, self.drift))
        return irrigated

    def value(self, elapsed: float) -> float:
        return self.base + self.drift + random.gauss(0, 0.35)


class DeviceState:
    """单台设备的连续状态，保证相邻采样平滑变化而不是白噪声。"""

    def __init__(self, device_code: str, scenario: Scenario | None = None):
        self.device_code = device_code
        catalog = DEVICE_CATALOG.get(device_code, {})
        base = BASELINE.get(device_code, BASELINE["FJ-CITRUS-A01"])
        self.plot_code = catalog.get("plot_code", "A")
        self.type = catalog.get("type", "env")
        # V2.1 C-10：设备形态（露天地块 / 温室）决定是否上报 co2
        self.scenario_kind = catalog.get("scenario", "open_field")
        self.base = dict(base)
        self.phase_hours = _device_phase_hours(device_code)
        self.scenario = scenario or Scenario("normal", SIM_DEMO_ACCELERATION)
        self.soil = SoilPhysics(base["soil_moisture"])
        self.battery = base["battery"]
        # V2：指令造成的持续扰动窗口
        self.pesticide_until = 0.0
        self.ventilation_until = 0.0
        self.last_command: dict | None = None
        # 降雨速率（点/秒的等效水量，mm/s），由气象状态按地块喂入
        self.rain_rate = 0.0
        self.last_injected = False
        self.last_metrics: dict = {}

    # ---- 物理量生成 ----
    def _daily(self, amplitude: float, peak_hour: float, now: datetime) -> float:
        """日周期正弦：峰值出现在 peak_hour 左右，再叠加本机相位偏移。"""
        hour = now.hour + now.minute / 60.0 + now.second / 3600.0
        return amplitude * math.cos(
            2 * math.pi * (hour - peak_hour - self.phase_hours) / 24.0
        )

    def set_rain_rate(self, mm_per_s: float) -> None:
        """由气象状态喂入当前雨强（mm/s）。"""
        self.rain_rate = max(0.0, float(mm_per_s))

    def sample(self, sim_elapsed: float, real_elapsed: float | None = None,
               now: datetime | None = None) -> dict:
        """sim_elapsed = 模拟秒（已乘演示加速）；real_elapsed 用于电池等真实时间量。"""
        elapsed = max(float(sim_elapsed), 0.0)
        real_elapsed = max(float(real_elapsed if real_elapsed is not None else sim_elapsed), 0.0)
        now = now or local_now()
        now_ts = now.timestamp()
        hour = now.hour + now.minute / 60.0 + now.second / 3600.0

        temperature = self.base["temperature"] + self._daily(5.2, 14.0, now) + random.gauss(0, 0.35)
        humidity = self.base["humidity"] - self._daily(9.0, 14.0, now) + random.gauss(0, 1.1)
        soil_temp = self.base["soil_temp"] + self._daily(2.4, 16.0, now) + random.gauss(0, 0.2)

        # V2.1 C-5：演示场景是连续过程（对气温/湿度做时间插值覆盖）
        scene_temp, scene_humidity = self.scenario.ambient(self.plot_code, temperature, humidity, hour)
        if scene_temp is not None:
            temperature = scene_temp
        if scene_humidity is not None:
            humidity = scene_humidity

        # V2：下行指令造成的可观测扰动
        if now_ts < self.ventilation_until:
            temperature -= 1.8
            humidity -= 6.0
        if now_ts < self.pesticide_until:
            soil_temp -= 1.5
            humidity += 4.0

        humidity = max(5.0, min(100.0, humidity))

        # V2.1 C-1/C-2：土壤墒情完全由 SoilPhysics 推进（蒸散 + 降雨 + 灌溉）
        rain_mm = self.rain_rate * real_elapsed  # 降雨按真实时间计（气象模块是权威）
        self.soil.step(elapsed, temperature, humidity, rain_mm)
        # 干旱场景：把墒情按过程强拉向目标值（仍可被灌溉指令叠加）
        target = self.scenario.soil_target(self.plot_code, self.base["soil_moisture"])
        if target is not None:
            current = self.soil.base + self.soil.drift
            self.soil.drift += (target - current) * 0.35
        soil_moisture = self.soil.value(elapsed)

        # V2.1 C-10：电池按真实小时衰减 0.02~0.06 点/小时（24h 掉 0.5~1.5 点）
        self.battery = max(
            5.0, self.battery - random.uniform(0.02, 0.06) * (real_elapsed / 3600.0)
        )

        # V2.1 C-10：上报字段按设备形态裁剪，不再所有设备同一组指标
        metrics: dict[str, float] = {"battery": round(self.battery, 1)}
        if self.type == "soil":
            metrics["soil_moisture"] = round(
                max(SOIL_MOISTURE_FLOOR, min(SOIL_MOISTURE_CEIL, soil_moisture)), 1
            )
            metrics["soil_temp"] = round(soil_temp, 1)
        else:
            metrics["temperature"] = round(temperature, 1)
            metrics["humidity"] = round(humidity, 1)
            if self.scenario_kind == "greenhouse":
                # 温室菇棚：夜间呼吸 + 通风降 CO₂
                co2 = (
                    self.base.get("co2", 800.0)
                    + self._daily(140.0, 6.0, now)
                    + random.gauss(0, 18.0)
                )
                if now_ts < self.ventilation_until:
                    co2 -= 220.0
                metrics["co2"] = round(max(300.0, min(2000.0, co2)), 1)

        # V2.1 C-5：默认不注入（SIM_BAD_PROBABILITY=0）；显式开启时打标记便于区分
        self.last_injected = False
        if SIM_BAD_PROBABILITY > 0 and random.random() < SIM_BAD_PROBABILITY:
            candidates = [name for name in OUT_OF_RANGE if name in metrics]
            if candidates:
                bad_metric = random.choice(candidates)
                metrics[bad_metric] = round(random.choice(OUT_OF_RANGE[bad_metric]), 1)
                self.last_injected = True

        self.last_metrics = metrics
        return metrics

    # ---- V2：指令真正改变行为 ----
    def apply_command(self, action: str, params: dict) -> tuple[bool, str]:
        """执行下行指令，返回 (是否成功, 中文说明)。会真实改变后续采样。"""
        now_ts = time.time()
        params = params or {}
        if action == "irrigation_on":
            requested = params.get("duration_min")
            minutes = _minutes(params, "duration_min", 30.0)
            clipped = ""
            try:
                if requested is not None and float(requested) > minutes:
                    clipped = f"（请求 {float(requested):.0f} 分钟，已按上限 {MAX_EFFECT_MINUTES:.0f} 分钟执行）"
            except (TypeError, ValueError):
                clipped = ""
            rate, real_seconds = self.soil.start_irrigation(now_ts, minutes)
            dose = SIM_IRRIGATION_RATE_PCT_PER_S * 60.0 * minutes
            self.last_command = {"action": action, "params": params, "ts": iso(local_now())}
            return True, (
                f"灌溉已开启：{SIM_IRRIGATION_RATE_PCT_PER_S}%/模拟秒 × {SIM_DEMO_ACCELERATION:.0f} 倍加速"
                f" = {_effective_irrigation_rate():.4f}%/真实秒；持续 {minutes:.0f} 模拟分钟{clipped}"
                f"（约 {real_seconds / 60.0:.1f} 真实分钟），预计补水 {dose:.1f} 个百分点"
                f"（当前墒情偏移 {self.soil.drift:.1f} 点）"
            )
        if action == "irrigation_off":
            self.soil.stop_irrigation()
            self.last_command = {"action": action, "params": params, "ts": iso(local_now())}
            return True, f"灌溉已关闭：停止补水（当前墒情偏移 {self.soil.drift:.1f} 点）"
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

    def payload(self, sim_elapsed: float, real_elapsed: float | None = None,
                now: datetime | None = None) -> str:
        now = now or local_now()
        body = {
            "device_code": self.device_code,
            "plot_code": self.plot_code,
            "type": self.type,
            "ts": iso(now),
        }
        body.update(self.sample(sim_elapsed, real_elapsed, now))
        # V2.1：让前端与答辩都能说清"这是 N 倍时间压缩的演示"
        body["sim_acceleration"] = SIM_DEMO_ACCELERATION
        body["scenario"] = SIM_SCENARIO
        if self.last_injected:
            body["injected"] = True
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
    scenario = Scenario(SIM_SCENARIO, SIM_DEMO_ACCELERATION)
    _states = {code: DeviceState(code, scenario) for code in device_codes}
    states = _states

    # V2：气象按地块发布（地块集合来自所选设备）
    plots = sorted({s.plot_code for s in states.values()})
    weather_states = {code: weather_mod.WeatherState(code) for code in plots}

    print(
        f"[simulator] 目标 {MQTT_HOST}:{MQTT_PORT}，间隔 {SIM_INTERVAL_SECONDS}s，"
        f"设备 {device_codes}，越界概率 {SIM_BAD_PROBABILITY}，丢包概率 {SIM_PACKET_LOSS}",
        flush=True,
    )
    print(
        f"[simulator] 灌溉速率 {SIM_IRRIGATION_RATE_PCT_PER_S}%/模拟秒 × 演示加速 {SIM_DEMO_ACCELERATION}"
        f" = 对真实时间 {_effective_irrigation_rate():.4f}%/真实秒；场景 {SIM_SCENARIO}",
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
    dropped = 0
    rain_by_plot: dict[str, float] = {code: 0.0 for code in plots}
    try:
        while _running:
            now = time.time()
            elapsed = max(now - last, 0.001)
            last = now
            scenario.tick(now)

            if client.is_connected():
                warned = False
                # 气象先于遥测发布：本轮雨强喂给同地块的墒情物理
                if WEATHER_ENABLED and now - last_weather >= WEATHER_INTERVAL_SECONDS:
                    last_weather = now
                    span = max(WEATHER_INTERVAL_SECONDS, 1.0)
                    for plot_code, wstate in weather_states.items():
                        data = wstate.sample(span)
                        body = {"plot_code": plot_code, "ts": iso(local_now())}
                        body.update(data)
                        client.publish(
                            wstate.topic(), json.dumps(body, ensure_ascii=False), qos=0, retain=False
                        )
                        rain_by_plot[plot_code] = float(data.get("rainfall_mm") or 0.0) / span
                    print(
                        f"[simulator] 已发布气象 {len(weather_states)} 条（地块 {plots}）"
                        f" ts={iso(local_now())} 24h雨量={ {c: round(w.precip_mm_24h(), 1) for c, w in weather_states.items()} }",
                        flush=True,
                    )

                sim_elapsed = elapsed * SIM_DEMO_ACCELERATION
                for code, state in states.items():
                    state.set_rain_rate(rain_by_plot.get(state.plot_code, 0.0))
                    # V2.1 C-10：按概率整条丢弃，演示「数据缺失」（默认 0 = 不丢）
                    if SIM_PACKET_LOSS > 0 and random.random() < SIM_PACKET_LOSS:
                        dropped += 1
                        continue
                    client.publish(
                        state.topic(), state.payload(sim_elapsed, elapsed), qos=0, retain=False
                    )
                tick += 1
                if tick % 12 == 1:
                    print(
                        f"[simulator] 已发布 {tick} 轮，最新 ts={iso(local_now())}"
                        f"，累计丢弃 {dropped} 条",
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
