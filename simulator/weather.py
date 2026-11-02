"""气象 Mock 数据源（V2_PLAN.md 第 3 节）：向 agri/weather/{plot_code} 周期发布。

每 WEATHER_INTERVAL_SECONDS（默认 30）为每个地块发布一条：
{"plot_code","ts","temperature","humidity","rainfall_mm","wind_dir","wind_level","condition"}

用日周期 + 缓慢随机游走，保证相邻两条平滑、且不同地块有差异。
仅依赖标准库。
"""
from __future__ import annotations

import json
import math
import os
import random
from datetime import datetime

WEATHER_INTERVAL_SECONDS = float(os.getenv("WEATHER_INTERVAL_SECONDS") or 30)
WEATHER_TOPIC_TEMPLATE = os.getenv("MQTT_WEATHER_TOPIC_TEMPLATE") or "agri/weather/{plot_code}"

WIND_DIRS = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]

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
        self.rain_event_until = 0.0
        self.drift = 0.0

    def _daily(self, amplitude: float, peak_hour: float = 15.0) -> float:
        now = local_now()
        hour = now.hour + now.minute / 60.0 + now.second / 3600.0
        return amplitude * math.cos(2 * math.pi * (hour - peak_hour) / 24.0)

    def sample(self, elapsed: float) -> dict:
        # 缓慢随机游走，避免两条气象数据跳变
        self.drift += random.gauss(0, 0.18) * max(elapsed, 1.0) ** 0.5
        self.drift = max(-6.0, min(6.0, self.drift))

        temperature = self.base["temperature"] + self._daily(5.0) + self.drift + random.gauss(0, 0.3)
        humidity = self.base["humidity"] - self._daily(14.0) - self.drift + random.gauss(0, 1.2)
        humidity = max(15.0, min(99.0, humidity))

        now_ts = local_now().timestamp()
        # 偶发降雨过程（持续 10~25 分钟），其余时间无降水
        if now_ts > self.rain_event_until and random.random() < 0.03:
            self.rain_event_until = now_ts + random.uniform(600, 1500)
        raining = now_ts < self.rain_event_until
        rainfall = round(random.uniform(0.2, 2.4), 1) if raining else 0.0
        if raining:
            humidity = min(99.0, humidity + 8.0)
            temperature -= 1.2

        hour = local_now().hour
        wind_level = max(0, min(6, int(round(self.base["wind_level"] + self._daily(1.6) + random.uniform(-0.6, 0.6)))))
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
            "rainfall_mm": rainfall,
            "wind_dir": WIND_DIRS[hour % len(WIND_DIRS)],
            "wind_level": wind_level,
            "condition": condition,
        }

    def topic(self) -> str:
        return WEATHER_TOPIC_TEMPLATE.format(plot_code=self.plot_code)

    def payload(self, elapsed: float) -> str:
        body = {"plot_code": self.plot_code, "ts": iso(local_now())}
        body.update(self.sample(elapsed))
        return json.dumps(body, ensure_ascii=False)
