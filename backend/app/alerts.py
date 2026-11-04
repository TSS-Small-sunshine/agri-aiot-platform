"""阈值规则引擎（契约第 6 节 v1.1 + V2.1 C-4）。

契约原文（逐条实现，不自行扩张）：
- temperature：正常 15~35℃；>38 或 <5 → critical；35~38 或 5~15 → warning
- humidity   ：正常 40~92%；92~97 或 <40 → warning；>97 或 <30 → critical
- soil_moisture：正常 35~80%；<35 → warning；<25 → critical

v1.1 变更：humidity 由原先只定义 <30/>95 改为对称双档，30~40 与 85~95 不再是静默带。

V2.1 C-4 变更（ClawsGo 审计：福建夜间高湿天天刷告警）：
1. humidity 正常上限由 85 放宽到 92、critical_max 由 95 放宽到 97（福建柑橘产区夜间
   85~95% 是常态，旧上限会每天刷一批无意义告警）。
2. 湿度告警加前置条件：只有 temperature >= HUMIDITY_ALERT_MIN_TEMPERATURE 才判湿度告警
   —— 病害（炭疽/溃疡）需要"高温高湿"同时成立，低温高湿不构成农事风险。
   温度缺失时不判 humidity 告警（宁可漏报，不可凭半条数据误报）。
3. 连续越界抑制：任何指标必须最近 ALERT_SUSTAINED_SAMPLES 个采样点连续越界才告警，
   单点毛刺不告警。ALERT_COOLDOWN_SECONDS 作为第二道闸保留。
"""
from __future__ import annotations

import os

from . import config, db
from .timeutil import now_iso

METRIC_LABELS = {
    "temperature": ("空气温度", "℃"),
    "humidity": ("空气湿度", "%"),
    "soil_moisture": ("土壤墒情", "%"),
}

# V2.1 C-4：连续越界抑制的采样点数（模拟器 5s 一条 → 3 点 ≈ 15 秒）。
ALERT_SUSTAINED_SAMPLES = 3
# V2.1 C-4：湿度告警的温度前置条件（℃）；低于该温度的高湿不告警。
HUMIDITY_ALERT_MIN_TEMPERATURE = 20.0

# 同一设备+指标+级别在窗口内只落一条告警，避免模拟器 5s 一条把告警表刷爆。
# 契约 v1.1 §2 已收录该变量；设为 0 表示关闭冷却（每次越界都落库）。
# 注意：不能用 "os.getenv(...) or 300" —— 字符串 "0" 为真值但会绕过显式 0 的语义，
# 这里区分"未设置"与"显式 0"。
def _read_cooldown() -> int:
    raw = os.getenv("ALERT_COOLDOWN_SECONDS")
    if raw is None or raw.strip() == "":
        return 300
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return 300


ALERT_COOLDOWN_SECONDS = _read_cooldown()


def _fmt(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".") if value != int(value) else f"{int(value)}"


def evaluate_temperature(value: float) -> tuple[str, float] | None:
    cfg = config.THRESHOLDS["temperature"]
    if value > cfg["critical_max"]:
        return "critical", cfg["critical_max"]
    if value < cfg["critical_min"]:
        return "critical", cfg["critical_min"]
    if value > cfg["max"]:
        return "warning", cfg["max"]
    if value < cfg["min"]:
        return "warning", cfg["min"]
    return None


def evaluate_humidity(value: float) -> tuple[str, float] | None:
    cfg = config.THRESHOLDS["humidity"]
    if value > cfg["critical_max"]:
        return "critical", cfg["critical_max"]
    if value < cfg["critical_min"]:
        return "critical", cfg["critical_min"]
    if value > cfg["max"]:
        return "warning", cfg["max"]
    if value < cfg["min"]:
        return "warning", cfg["min"]
    return None


def evaluate_soil_moisture(value: float) -> tuple[str, float] | None:
    cfg = config.THRESHOLDS["soil_moisture"]
    if value < cfg["critical_min"]:
        return "critical", cfg["critical_min"]
    if value < cfg["min"]:
        return "warning", cfg["min"]
    if value > cfg["max"]:
        return "warning", cfg["max"]
    return None


EVALUATORS = {
    "temperature": evaluate_temperature,
    "humidity": evaluate_humidity,
    "soil_moisture": evaluate_soil_moisture,
}


def _device_name(device_code: str) -> str:
    row = db.query_one("SELECT name FROM devices WHERE device_code = ?", (device_code,))
    return row["name"] if row else device_code


def _recent_values(device_code: str, metric: str, count: int) -> list[float]:
    """取该设备该指标最近 count 个非空采样值（新→旧）。

    调用点保证本条遥测已先落库（见 mqtt_client._handle），所以列表首元素就是当前值。
    metric 只可能来自 EVALUATORS 的固定键，插值进 SQL 无注入风险，仍显式白名单校验。
    """
    if metric not in EVALUATORS:
        return []
    rows = db.query(
        f"""SELECT {metric} AS v FROM telemetry
            WHERE device_code = ? AND {metric} IS NOT NULL
            ORDER BY ts DESC, id DESC LIMIT ?""",
        (device_code, max(1, int(count))),
    )
    values: list[float] = []
    for row in rows:
        try:
            values.append(float(row["v"]))
        except (TypeError, ValueError):
            continue
    return values


def _sustained(device_code: str, metric: str) -> bool:
    """最近 ALERT_SUSTAINED_SAMPLES 个采样点是否**连续越界**（V2.1 C-4）。

    只要求"每一点都越界"，不要求级别完全一致：96→98→96 是同一场高湿过程的推进，
    级别以当前值为准；而 91→96 这种"从正常跨进越界"只有 2 点，不触发。
    样本不足（新设备刚上线）时不触发 —— 宁可漏报，不凭 1~2 点误报。
    """
    evaluator = EVALUATORS.get(metric)
    if evaluator is None:
        return False
    values = _recent_values(device_code, metric, ALERT_SUSTAINED_SAMPLES)
    if len(values) < ALERT_SUSTAINED_SAMPLES:
        return False
    return all(evaluator(v) is not None for v in values)


def _humidity_allowed(metrics: dict) -> tuple[bool, str]:
    """湿度告警前置条件（V2.1 C-4）：需要同时高温。返回 (是否允许, 说明)。"""
    raw = metrics.get("temperature")
    if raw is None:
        return False, f"温度缺失，不判湿度告警（需 ≥{_fmt(HUMIDITY_ALERT_MIN_TEMPERATURE)}℃）"
    try:
        temperature = float(raw)
    except (TypeError, ValueError):
        return False, f"温度非数值，不判湿度告警（需 ≥{_fmt(HUMIDITY_ALERT_MIN_TEMPERATURE)}℃）"
    if temperature < HUMIDITY_ALERT_MIN_TEMPERATURE:
        return False, f"当前气温 {_fmt(temperature)}℃ 低于 {_fmt(HUMIDITY_ALERT_MIN_TEMPERATURE)}℃，低温高湿不构成病害条件"
    return True, ""


def _recent_duplicate(
    device_code: str, metric: str, level: str, threshold: float, cutoff: str | None
) -> bool:
    """冷却窗口内同键只保留一条。

    键 = (device_code, metric, level, threshold)。threshold 用来区分"越过了哪条边界"：
    湿度 38（低于下限 40）与 92（高于上限 85）虽同为 warning，却是两种不同的农事状况，
    若只用 level 做键会互相顶掉——实测会把 92 的告警整条吞掉。加入 threshold 后
    同一条边界的高频重复（模拟器 5s 一条）仍然只落一条，防刷表的目的不变。
    """
    if cutoff is None:  # 冷却关闭：不做去重，每次越界都落库
        return False
    row = db.query_one(
        """SELECT id FROM alerts
           WHERE device_code = ? AND metric = ? AND level = ? AND threshold = ? AND created_at >= ?
           LIMIT 1""",
        (device_code, metric, level, threshold, cutoff),
    )
    return row is not None


def _cooldown_cutoff() -> str | None:
    if ALERT_COOLDOWN_SECONDS <= 0:
        return None
    from .timeutil import cutoff_iso
    return cutoff_iso(ALERT_COOLDOWN_SECONDS / 3600.0)


def evaluate(device_code: str, metrics: dict) -> list[dict]:
    """对一条遥测做阈值判定，越界且持续则落库。返回本次真正写入的告警列表。"""
    created = now_iso()
    cutoff = _cooldown_cutoff()
    name = _device_name(device_code)
    fired: list[dict] = []

    for metric, evaluator in EVALUATORS.items():
        value = metrics.get(metric)
        if value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue

        if metric == "humidity":
            allowed, _reason = _humidity_allowed(metrics)
            if not allowed:
                continue

        verdict = evaluator(value)
        if verdict is None:
            continue
        level, threshold = verdict

        # V2.1 C-4：连续 3 点越界才告警，单点毛刺不告警。
        if not _sustained(device_code, metric):
            continue

        if _recent_duplicate(device_code, metric, level, threshold, cutoff):
            continue

        label, unit = METRIC_LABELS[metric]
        direction = "高于上限" if value > threshold else "低于下限"
        message = (
            f"{name} {label} {_fmt(value)}{unit} {direction} {_fmt(threshold)}{unit}"
        )
        alert_id = db.insert(
            """INSERT INTO alerts (device_code, metric, value, threshold, level, message, acked, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 0, ?)""",
            (device_code, metric, value, threshold, level, message, created),
        )
        fired.append({"id": alert_id, "metric": metric, "level": level, "message": message})

    return fired
