"""一键演示用的历史数据灌入脚本。

直接写 SQLite（复用 backend/app 的 DDL 与设备清单，避免两处漂移），
默认灌入过去 24 小时、每 5 分钟一条、共 4 台设备（每台 288 个点）。

用法：
    python scripts/seed_history.py
    python scripts/seed_history.py --hours 48 --step-minutes 10 --db data/agri.db

仅依赖标准库（后端运行时依赖不会被本脚本引入）。
"""
from __future__ import annotations

import argparse
import math
import random
import sys
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app import config, db  # noqa: E402
from app.timeutil import LOCAL_TZ, now, to_iso  # noqa: E402

# 与模拟器一致的基线，保证"历史数据"与"实时数据"接得上
BASELINE = {
    "FJ-CITRUS-A01": {"temperature": 25.5, "humidity": 70.0, "soil_moisture": 58.0, "soil_temp": 23.0, "battery": 94.0},
    "FJ-CITRUS-A02": {"temperature": 25.0, "humidity": 68.0, "soil_moisture": 52.0, "soil_temp": 22.5, "battery": 91.0},
    "FJ-CITRUS-B01": {"temperature": 26.5, "humidity": 66.0, "soil_moisture": 61.0, "soil_temp": 24.0, "battery": 88.0},
    "FJ-CITRUS-B02": {"temperature": 26.0, "humidity": 64.0, "soil_moisture": 47.0, "soil_temp": 23.5, "battery": 85.0},
}

# 历史中按概率制造少量越界点，让 /api/alerts 与图表"有故事"
OUT_OF_RANGE = {
    "temperature": [4.2, 36.8, 39.1],
    "humidity": [26.5, 96.8],
    "soil_moisture": [21.0, 29.5, 84.0],
}


def daily_cycle(moment, amplitude: float, peak_hour: float) -> float:
    hour = moment.hour + moment.minute / 60.0
    return amplitude * math.cos(2 * math.pi * (hour - peak_hour) / 24.0)


def build_rows(hours: float, step_minutes: float, bad_probability: float) -> list[tuple]:
    end = now().replace(second=0, microsecond=0)
    step = timedelta(minutes=step_minutes)
    steps = int((hours * 60) / step_minutes)
    start = end - step * steps

    rows: list[tuple] = []
    for device in config.DEVICES:
        code = device["device_code"]
        base = BASELINE.get(code, BASELINE["FJ-CITRUS-A01"])
        drift = 0.0
        battery = base["battery"]

        for index in range(steps + 1):
            moment = start + step * index
            drift -= 0.010 * (step_minutes * 60) / 60.0
            if drift < -6.0:
                drift = random.uniform(2.0, 6.0)  # 灌溉回升

            temperature = base["temperature"] + daily_cycle(moment, 5.2, 14.0) + random.gauss(0, 0.4)
            humidity = base["humidity"] - daily_cycle(moment, 9.0, 14.0) + random.gauss(0, 1.2)
            soil_moisture = base["soil_moisture"] + drift + random.gauss(0, 0.4)
            soil_temp = base["soil_temp"] + daily_cycle(moment, 2.4, 16.0) + random.gauss(0, 0.25)
            battery = max(5.0, battery - random.uniform(0.0008, 0.003))

            metrics = {
                "temperature": round(temperature, 1),
                "humidity": round(max(5.0, min(100.0, humidity)), 1),
                "soil_moisture": round(max(2.0, min(100.0, soil_moisture)), 1),
                "soil_temp": round(soil_temp, 1),
                "battery": round(battery, 1),
            }
            if random.random() < bad_probability:
                metric = random.choice(list(OUT_OF_RANGE))
                metrics[metric] = round(random.choice(OUT_OF_RANGE[metric]), 1)

            rows.append((
                code, to_iso(moment.astimezone(LOCAL_TZ)),
                metrics["temperature"], metrics["humidity"], metrics["soil_moisture"],
                metrics["soil_temp"], metrics["battery"], None,
            ))

    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="灌入过去 N 小时的演示历史数据")
    parser.add_argument("--hours", type=float, default=24, help="回溯小时数（默认 24）")
    parser.add_argument("--step-minutes", type=float, default=5, help="采样间隔分钟（默认 5）")
    parser.add_argument("--db", default=None, help="SQLite 文件路径（默认取 DB_PATH 环境变量）")
    parser.add_argument("--bad-probability", type=float, default=0.03, help="越界点概率（默认 0.03）")
    parser.add_argument("--clear", action="store_true", help="先清空 telemetry 表再灌入")
    args = parser.parse_args()

    if args.db:
        config.DB_PATH = Path(args.db).resolve()

    if args.hours <= 0 or args.step_minutes <= 0:
        print("--hours 与 --step-minutes 必须为正数", file=sys.stderr)
        return 2

    db.init_db()
    if args.clear:
        db.execute("DELETE FROM telemetry")

    rows = build_rows(args.hours, args.step_minutes, args.bad_probability)
    db.executemany(
        """INSERT INTO telemetry
           (device_code, ts, temperature, humidity, soil_moisture, soil_temp, battery, raw)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )

    # 让设备立刻显示为 online
    for device in config.DEVICES:
        db.touch_device(device["device_code"], to_iso(now()))

    per_device = len(rows) // max(len(config.DEVICES), 1)
    print(
        f"[seed] 已写入 {len(rows)} 条遥测（{len(config.DEVICES)} 台设备 × 约 {per_device} 点），"
        f"跨度 {args.hours}h / 步长 {args.step_minutes}min"
    )
    print(f"[seed] 数据库：{config.DB_PATH}")

    summary = db.query_one(
        """SELECT COUNT(*) AS samples, AVG(temperature) AS t, AVG(humidity) AS h, AVG(soil_moisture) AS s
           FROM telemetry WHERE ts >= ?""",
        (to_iso(now() - timedelta(hours=args.hours)),),
    )
    print(
        f"[seed] 校验（近 {args.hours}h）：samples={summary['samples']} "
        f"temp_avg={summary['t']:.1f} humidity_avg={summary['h']:.1f} soil_avg={summary['s']:.1f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
