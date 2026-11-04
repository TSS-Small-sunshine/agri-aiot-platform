"""气象 Mock 数据源（V2_PLAN.md 第 3 节；V2.1 C-3 真实化）。

每 WEATHER_INTERVAL_SECONDS（默认 30）为每个地块发布一条：
{"plot_code","ts","temperature","humidity","rainfall_mm","wind_dir","wind_level",
 "condition","precip_mm_24h"}

V2.1 C-3 变更（旧版实测出现过"47 分钟下 226mm 雨"，一眼假）：
- 单场降雨 5~60 分钟、雨强 0.5~8 mm/h，起雨概率随季节与时段变化（不再恒定 3%）；
- 硬上限：单场累计 <=25mm、任意 24 小时窗口累计 <=40mm
  （起雨时即按 24h 剩余额度与单场上限夹紧雨强，过程内再逐条夹紧，双重保险）；
- 风向由"整点跳变"改为连续随机游走（每 0.5~2 小时换一次目标，逐步靠拢）；
- payload 新增 precip_mm_24h（滚动 24 小时累计降雨）。

仅依赖标准库。
"""
from __future__ import annotations

import json
import math
import os
import random
from collections import deque
from datetime import datetime

WEATHER_INTERVAL_SECONDS = float(os.getenv("WEATHER_INTERVAL_SECONDS") or 30)
WEATHER_TOPIC_TEMPLATE = os.getenv("MQTT_WEATHER_TOPIC_TEMPLATE") or "agri/weather/{plot_code}"

WIND_DIRS = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]

# ---- V2.1 C-3：降雨物理参数（契约级硬上限，不得放宽）----
RAIN_EVENT_MIN_MINUTES = 5.0
RAIN_EVENT_MAX_MINUTES = 60.0
RAIN_INTENSITY_MIN_MM_H = 0.5
RAIN_INTENSITY_MAX_MM_H = 8.0
RAIN_EVENT_MAX_MM = 25.0
RAIN_24H_MAX_MM = 40.0
RAIN_WINDOW_SECONDS = 24 * 3600.0
RAIN_BASE_START_PROBABILITY = 0.0012  # 每个采样点的起雨概率基数

# 福建南平：3~6 月前汛期多雨，7~9 月台风季次之，冬季干冷
MONTH_RAIN_FACTOR = {
    1: 0.30, 2: 0.40, 3: 1.00, 4: 1.30, 5: 1.60, 6: 1.80,
    7: 1.30, 8: 1.20, 9: 0.90, 10: 0.50, 11: 0.35, 12: 0.25,
}


def _season_factor(month: int) -> float:
    return MONTH_RAIN_FACTOR.get(month, 0.60)


def _hour_factor(hour: int) -> float:
    """午后对流性降雨概率更高，凌晨最低。"""
    if 13 <= hour <= 19:
        return 1.60
    if 0 <= hour <= 6:
        return 0.50
    return 1.00


# 每地块气象基线
BASELINE = {
    "A": {"temperature": 26.5, "humidity": 68.0, "wind_level": 2},
    "B": {"temperature": 27.2, "humidity": 64.0, "wind_level": 3},
}


def local_now() -> datetime:
    return datetime.now().astimezone()


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


class WeatherState:
    """单地块的连续气象状态。"""

    def __init__(self, plot_code: str):
        self.plot_code = plot_code
        base = BASELINE.get(plot_code, {"temperature": 26.0, "humidity": 66.0, "wind_level": 2})
        self.base = dict(base)
        self.drift = 0.0
        # V2.1：当前雨强（mm/h），遥测侧据此给土壤墒情补水
        self.rain_intensity = 0.0
        self.rain_event_until = 0.0
        self.rain_event_started = 0.0
        self.rain_event_total = 0.0
        self.rain_event_limit = 0.0
        self.max_event_total = 0.0
        self.rain_history: deque = deque()
        # 风向：连续随机游走（浮点方位索引）
        self.wind_index = float(WIND_DIRS.index("东") if plot_code == "A" else WIND_DIRS.index("东南"))
        self.wind_target = self.wind_index
        self.wind_shift_until = 0.0

    # ---- 日周期 ----
    def _daily(self, amplitude: float, now: datetime, peak_hour: float = 15.0) -> float:
        hour = now.hour + now.minute / 60.0 + now.second / 3600.0
        return amplitude * math.cos(2 * math.pi * (hour - peak_hour) / 24.0)

    # ---- V2.1 C-3：降雨事件 ----
    def _prune_rain(self, now_ts: float) -> None:
        cutoff = now_ts - RAIN_WINDOW_SECONDS
        while self.rain_history and self.rain_history[0][0] < cutoff:
            self.rain_history.popleft()

    def _record_rain(self, now_ts: float, mm: float) -> None:
        if mm > 0:
            self.rain_history.append((now_ts, mm))
        self._prune_rain(now_ts)

    def precip_mm_24h(self, now_ts: float | None = None) -> float:
        ts = now_ts if now_ts is not None else local_now().timestamp()
        self._prune_rain(ts)
        return sum(mm for _, mm in self.rain_history)

    def _maybe_start_rain(self, now: datetime, now_ts: float) -> None:
        probability = RAIN_BASE_START_PROBABILITY * _season_factor(now.month) * _hour_factor(now.hour)
        if random.random() >= probability:
            return
        budget = RAIN_24H_MAX_MM - self.precip_mm_24h(now_ts)
        minimum_event_mm = RAIN_INTENSITY_MIN_MM_H * (RAIN_EVENT_MIN_MINUTES / 60.0)
        if budget <= minimum_event_mm:
            return  # 24h 额度已用尽：本窗口不再起雨（硬上限 40mm）
        duration_s = random.uniform(RAIN_EVENT_MIN_MINUTES, RAIN_EVENT_MAX_MINUTES) * 60.0
        hours = duration_s / 3600.0
        intensity = random.uniform(RAIN_INTENSITY_MIN_MM_H, RAIN_INTENSITY_MAX_MM_H)
        # 单场 <=25mm 与 24h 剩余额度双重夹紧
        intensity = min(intensity, RAIN_EVENT_MAX_MM / hours, budget / hours)
        if intensity < RAIN_INTENSITY_MIN_MM_H:
            return
        self.rain_intensity = intensity
        self.rain_event_until = now_ts + duration_s
        self.rain_event_started = now_ts
        self.rain_event_total = 0.0
        self.rain_event_limit = min(RAIN_EVENT_MAX_MM, budget)
        print(
            f"[weather] 起雨 plot={self.plot_code} 时长={duration_s / 60:.0f}分钟 "
            f"雨强={intensity:.2f}mm/h 预计累计={intensity * hours:.2f}mm "
            f"24h已用={RAIN_24H_MAX_MM - budget:.1f}mm",
            flush=True,
        )

    def _end_rain(self, now_ts: float) -> None:
        if self.rain_event_total > 0:
            print(
                f"[weather] 雨停 plot={self.plot_code} "
                f"实际时长={(now_ts - self.rain_event_started) / 60:.0f}分钟 "
                f"本场累计={self.rain_event_total:.2f}mm（上限 {RAIN_EVENT_MAX_MM:.0f}mm）",
                flush=True,
            )
        self.rain_intensity = 0.0
        self.rain_event_until = 0.0

    def _rain_step(self, now: datetime, now_ts: float, elapsed: float) -> float:
        if now_ts >= self.rain_event_until:
            if self.rain_intensity > 0:
                self._end_rain(now_ts)
            self._maybe_start_rain(now, now_ts)
        if self.rain_intensity <= 0:
            return 0.0
        mm = self.rain_intensity * elapsed / 3600.0
        remain = RAIN_EVENT_MAX_MM - self.rain_event_total
        if mm > remain:
            mm = max(0.0, remain)
        self.rain_event_total += mm
        self.max_event_total = max(self.max_event_total, self.rain_event_total)
        self._record_rain(now_ts, mm)
        if self.rain_event_total >= RAIN_EVENT_MAX_MM - 1e-9:
            self._end_rain(now_ts)
        return mm

    # ---- 风向 ----
    def _wind_dir(self, elapsed: float, now_ts: float) -> str:
        if now_ts > self.wind_shift_until:
            self.wind_shift_until = now_ts + random.uniform(1800, 7200)
            self.wind_target = (self.wind_target + random.choice([-2, -1, 1, 1, 2])) % len(WIND_DIRS)
        span = float(len(WIND_DIRS))
        diff = (self.wind_target - self.wind_index + span / 2.0) % span - span / 2.0
        step = min(abs(diff), random.uniform(0.05, 0.15))
        self.wind_index = (self.wind_index + (step if diff >= 0 else -step)) % span
        return WIND_DIRS[int(round(self.wind_index)) % len(WIND_DIRS)]

    def sample(self, elapsed: float, now: datetime | None = None) -> dict:
        now = now or local_now()
        now_ts = now.timestamp()
        elapsed = max(float(elapsed), 1.0)

        # 缓慢随机游走，避免两条气象数据跳变
        self.drift += random.gauss(0, 0.18) * elapsed ** 0.5
        self.drift = max(-6.0, min(6.0, self.drift))

        temperature = self.base["temperature"] + self._daily(5.0, now) + self.drift + random.gauss(0, 0.3)
        humidity = self.base["humidity"] - self._daily(14.0, now) - self.drift + random.gauss(0, 1.2)
        humidity = max(15.0, min(99.0, humidity))

        rainfall = self._rain_step(now, now_ts, elapsed)
        if rainfall > 0:
            humidity = min(99.0, humidity + 8.0)
            temperature -= 1.2

        hour = now.hour
        wind_level = max(
            0, min(6, int(round(self.base["wind_level"] + self._daily(1.6, now) + random.uniform(-0.6, 0.6))))
        )
        if rainfall >= 2.0:
            condition = "中雨"
        elif rainfall > 0:
            condition = "小雨"
        elif humidity > 88:
            condition = "阴"
        elif 6 <= hour <= 18:
            condition = "晴"
        else:
            condition = "多云"

        return {
            "temperature": round(temperature, 1),
            "humidity": round(humidity, 1),
            "rainfall_mm": round(rainfall, 2),
            "wind_dir": self._wind_dir(elapsed, now_ts),
            "wind_level": wind_level,
            "condition": condition,
            "precip_mm_24h": round(self.precip_mm_24h(now_ts), 2),
        }

    def topic(self) -> str:
        return WEATHER_TOPIC_TEMPLATE.format(plot_code=self.plot_code)

    def payload(self, elapsed: float, now: datetime | None = None) -> str:
        now = now or local_now()
        body = {"plot_code": self.plot_code, "ts": iso(now)}
        body.update(self.sample(elapsed, now))
        return json.dumps(body, ensure_ascii=False)
