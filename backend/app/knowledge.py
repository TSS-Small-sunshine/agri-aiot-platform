"""农学先验规则引擎（V2_PLAN.md 第 8.1 节最后一步、第 13 节第 5 条）。

**完全独立于大模型**：只用本地规则与配置口径算出结构化结论，
既用于降级路径（source=fallback 时的同结构 JSON），
也用于主模型路径的交叉校验（偏差 >15 个百分点即以后端先验为准）。

口径（冻结，答辩口径）：
- 亩均滴灌耗电 POWER_KWH_PER_MU = 0.15 kWh/亩；
- 水分胁迫减产按「缺水深度 × 持续时间」在 15~25% 区间线性插值；
- 无水分胁迫时减产为 0（不虚报）；
- V2.1 C-1：灌溉时长由 config.SIM_IRRIGATION_RATE_PCT_PER_S 反推，与模拟器共用同一速率，
  保证「按 duration_min 灌溉 rate×60×duration_min 个百分点」两侧自洽（误差 ≤1 点）。

本模块**不访问网络、不访问数据库**，纯函数，便于单测与答辩讲解。
"""
from __future__ import annotations

import json

from . import config
from .timeutil import now_iso


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _num(value, unit: str = "") -> str:
    """诚实渲染：无采样时显示「暂无数据」，绝不显示字面 None。"""
    return "暂无数据" if value is None else f"{value}{unit}"


# ---------------- 规则表（白盒要"真"，每条规则可解释） ----------------
def _duration_factor(hours_below_min: float) -> float:
    """持续时间因子：0h→0，≥24h→1，中间线性。"""
    return _clamp(hours_below_min / 24.0, 0.0, 1.0)


def _depth_factor(soil_moisture: float, soil_threshold: dict) -> float:
    """缺水深度因子：达到正常下限→0，跌到 critical_min 及以下→1。"""
    low = _f(soil_threshold.get("min"), 35.0)
    critical = _f(soil_threshold.get("critical_min"), 25.0)
    span = max(low - critical, 0.001)
    return _clamp((low - soil_moisture) / span, 0.0, 1.0)


def match_rules(context: dict) -> list[dict]:
    """逐条评估农学规则，返回命中与未命中（白盒第二步要展示真实命中情况）。"""
    metrics = context["metrics"]
    thresholds = context["thresholds"]
    plot = context["plot"]
    soil = metrics.get("soil_moisture")
    temp = metrics.get("temperature")
    humidity = metrics.get("humidity")
    hours_below = _f(context.get("hours_below_min"))
    area_mu = _f(plot.get("area_mu"), 1.0)

    soil_th = thresholds["soil_moisture"]
    temp_th = thresholds["temperature"]
    hum_th = thresholds["humidity"]

    rules: list[dict] = []

    # 规则 1：水分胁迫（口径 15~25%）
    depth = _depth_factor(soil, soil_th) if soil is not None else 0.0
    dur = _duration_factor(hours_below)
    if soil is None:
        rules.append({"rule": "土壤墒情 < 正常下限且持续 → 减产 15~25%", "hit": False,
                      "detail": "本窗口无墒情采样，无法判定"})
    elif soil >= soil_th["min"]:
        rules.append({"rule": "土壤墒情 < 正常下限且持续 → 减产 15~25%", "hit": False,
                      "detail": f"墒情 {soil}% ≥ 正常下限 {soil_th['min']}%，无水分胁迫"})
    else:
        loss = config.YIELD_LOSS_MIN_PCT + 0.5 * (depth + dur) * (
            config.YIELD_LOSS_MAX_PCT - config.YIELD_LOSS_MIN_PCT
        )
        rules.append({
            "rule": "土壤墒情 < 正常下限且持续 → 减产 15~25%",
            "hit": True,
            "detail": (
                f"墒情 {soil}% < 正常下限 {soil_th['min']}%；缺水深度因子 {depth:.2f}"
                f"（临界 {soil_th['critical_min']}%），持续 {hours_below:.1f}h，"
                f"持续时间因子 {dur:.2f} → 减产 {loss:.1f}%"
            ),
        })

    # 规则 2：高温胁迫
    if temp is None:
        rules.append({"rule": "空气温度 > 上限 → 高温胁迫", "hit": False, "detail": "无温度采样"})
    elif temp > temp_th["critical_max"]:
        rules.append({"rule": "空气温度 > 上限 → 高温胁迫", "hit": True,
                      "detail": f"气温 {temp}℃ > critical {temp_th['critical_max']}℃，需降温干预"})
    elif temp > temp_th["max"]:
        rules.append({"rule": "空气温度 > 上限 → 高温胁迫", "hit": True,
                      "detail": f"气温 {temp}℃ > 正常上限 {temp_th['max']}℃，进入 warning 区"})
    else:
        rules.append({"rule": "空气温度 > 上限 → 高温胁迫", "hit": False,
                      "detail": f"气温 {temp}℃ 在正常区间 {temp_th['min']}~{temp_th['max']}℃"})

    # 规则 3：高湿病害风险
    if humidity is None:
        rules.append({"rule": "空气湿度 > 上限 → 炭疽/溃疡风险", "hit": False, "detail": "无湿度采样"})
    elif humidity > hum_th["max"]:
        rules.append({"rule": "空气湿度 > 上限 → 炭疽/溃疡风险", "hit": True,
                      "detail": f"湿度 {humidity}% > 正常上限 {hum_th['max']}%，建议通风降湿"})
    else:
        rules.append({"rule": "空气湿度 > 上限 → 炭疽/溃疡风险", "hit": False,
                      "detail": f"湿度 {humidity}% 未超上限 {hum_th['max']}%"})

    # 规则 4：灌溉耗电口径
    rules.append({
        "rule": f"亩均滴灌耗电 {config.POWER_KWH_PER_MU} kWh/亩",
        "hit": True,
        "detail": (
            f"地块 {plot.get('name')} 面积 {area_mu} 亩 × {config.POWER_KWH_PER_MU} kWh/亩"
            f" = {area_mu * config.POWER_KWH_PER_MU:.2f} kWh"
        ),
    })
    return rules


def evaluate(context: dict) -> dict:
    """先验模型主入口：返回结构化先验结论（不依赖大模型）。"""
    metrics = context["metrics"]
    thresholds = context["thresholds"]
    plot = context["plot"]
    area_mu = _f(plot.get("area_mu"), 1.0)

    soil = metrics.get("soil_moisture")
    temp = metrics.get("temperature")
    humidity = metrics.get("humidity")
    soil_th = thresholds["soil_moisture"]
    temp_th = thresholds["temperature"]
    hum_th = thresholds["humidity"]
    hours_below = _f(context.get("hours_below_min"))

    depth = _depth_factor(soil, soil_th) if soil is not None else 0.0
    dur = _duration_factor(hours_below)

    if soil is not None and soil < soil_th["min"]:
        severity = 0.5 * (depth + dur)
        yield_loss = config.YIELD_LOSS_MIN_PCT + severity * (
            config.YIELD_LOSS_MAX_PCT - config.YIELD_LOSS_MIN_PCT
        )
    else:
        severity = 0.0
        yield_loss = 0.0
    yield_loss = round(_clamp(yield_loss, 0.0, 100.0), 1)

    power_kwh = round(area_mu * config.POWER_KWH_PER_MU, 2)

    # 胁迫等级：综合墒情/温度/湿度
    level = "normal"
    if soil is not None and soil < soil_th["critical_min"]:
        level = "critical"
    elif temp is not None and temp > temp_th["critical_max"]:
        level = "critical"
    elif humidity is not None and humidity > hum_th["critical_max"]:
        level = "critical"
    elif soil is not None and soil < soil_th["min"]:
        level = "warn"
    elif temp is not None and temp > temp_th["max"]:
        level = "warn"
    elif humidity is not None and (humidity > hum_th["max"] or humidity < hum_th["min"]):
        level = "warn"

    interventions = build_interventions(context, level, power_kwh)
    rules = match_rules(context)

    return {
        "yield_loss_pct": yield_loss,
        "power_kwh": power_kwh,
        "severity": severity,
        "level": level,
        "depth_factor": round(depth, 3),
        "duration_factor": round(dur, 3),
        "hours_below_min": round(hours_below, 2),
        "rules": rules,
        "interventions": interventions,
    }


def _soil_device(plot: dict, context: dict) -> str:
    """挑一台墒情设备作为灌溉指令目标（soil 型优先）。"""
    codes = list(context.get("device_codes") or [])
    soil_like = [c for c in codes if c.endswith("02")]
    return (soil_like or codes or ["FJ-CITRUS-A02"])[0]


def build_interventions(context: dict, level: str, power_kwh: float) -> list[dict]:
    """干预策略 2~3 条，每条可执行 + 有量化收益（V2_PLAN.md 第 8.2 节硬性要求 3）。"""
    metrics = context["metrics"]
    thresholds = context["thresholds"]
    plot = context["plot"]
    soil = metrics.get("soil_moisture")
    temp = metrics.get("temperature")
    humidity = metrics.get("humidity")
    soil_th = thresholds["soil_moisture"]
    temp_th = thresholds["temperature"]
    hum_th = thresholds["humidity"]
    area_mu = _f(plot.get("area_mu"), 1.0)
    device_code = _soil_device(plot, context)

    plans: list[dict] = []

    # V2.1 C-1：滴灌速率（点/分钟）——与模拟器共用 config 里的同一个常量，改一处两侧同步。
    per_minute = config.SIM_IRRIGATION_RATE_PCT_PER_S * 60.0

    if soil is not None and soil < soil_th["min"]:
        # 目标墒情：灌到正常区间中位（min 与 max 的中点），由速率反推时长。
        target = (soil_th["min"] + soil_th["max"]) / 2.0
        deficit = max(target - soil, 0.0)
        duration_min = int(_clamp(round(deficit / per_minute), 10, 240))
        delta = round(min(per_minute * duration_min, 100.0), 1)
        plans.append({
            "action": "irrigation_on",
            "params": {"duration_min": duration_min},
            "device_code": device_code,
            "label": f"开启滴灌 {duration_min} 分钟",
            "sub": f"预计耗电 {power_kwh} 度 · 墒情回升 {delta}%",
            "effect": {
                "soil_moisture_delta": delta,
                "yield_recover_pct": round(min(14.0, delta * 0.8), 1),
            },
            "sku_keywords": ["滴灌带", "抗旱保水剂"],
            "reason": (
                f"墒情 {soil}% 低于正常下限 {soil_th['min']}%，"
                f"灌至区间中位 {target:.0f}% 需 {duration_min} 分钟"
                f"（滴灌 {config.SIM_IRRIGATION_RATE_PCT_PER_S}%/秒 × 60 = {per_minute:.2f} 点/分钟，"
                f"补水 {delta} 点）"
            ),
        })

    if temp is not None and temp > temp_th["max"]:
        plans.append({
            "action": "ventilation_on",
            "params": {"duration_min": 20},
            "device_code": next(
                (c for c in (context.get("device_codes") or []) if c.endswith("01")), "FJ-CITRUS-A01"
            ),
            "label": "开启通风降温 20 分钟",
            "sub": f"预计冠层降温 2~3℃ · 日灼风险下降",
            "effect": {"soil_moisture_delta": 0.0, "yield_recover_pct": 2.0},
            "sku_keywords": ["滴灌带"],
            "reason": f"气温 {temp}℃ 高于正常上限 {temp_th['max']}℃",
        })

    if humidity is not None and humidity > hum_th["max"]:
        plans.append({
            "action": "pesticide_dose",
            "params": {"dose_ml": 60, "target": "炭疽病预防"},
            "device_code": next(
                (c for c in (context.get("device_codes") or []) if c.endswith("01")), "FJ-CITRUS-A01"
            ),
            "label": "施药 60ml 预防炭疽病",
            "sub": "高湿 6 小时内完成 · 保护性杀菌剂",
            "effect": {"soil_moisture_delta": 0.0, "yield_recover_pct": 3.0},
            "sku_keywords": ["杀螨剂", "叶面钙肥"],
            "reason": f"湿度 {humidity}% 高于正常上限 {hum_th['max']}%，病害流行风险上升",
        })

    if not plans:
        # 数据正常时也给一条保守可执行项，保证前端绿色节点不空（口径不变）。
        plans.append({
            "action": "irrigation_on",
            "params": {"duration_min": 15},
            "device_code": device_code,
            "label": "预防性滴灌 15 分钟",
            "sub": f"维持墒情在 {soil_th['min']:.0f}~{soil_th['max']:.0f}% 区间",
            "effect": {
                "soil_moisture_delta": round(per_minute * 15.0, 1),
                "yield_recover_pct": 0.0,
            },
            "sku_keywords": ["滴灌带"],
            "reason": f"当前各项指标正常，按 {area_mu} 亩面积做一次预防性小水勤灌",
        })

    return plans[:3]


def summarize(context: dict, prior: dict) -> str:
    plot = context["plot"]
    metrics = context["metrics"]
    if prior["yield_loss_pct"] <= 0:
        return (
            f"{plot.get('name')} 当前墒情 {_num(metrics.get('soil_moisture'), '%')}、"
            f"气温 {_num(metrics.get('temperature'), '℃')}，各项指标处于正常区间，暂无减产风险。"
        )
    return (
        f"{plot.get('name')} 处于{_level_cn(prior['level'])}水分胁迫，"
        f"预计减产 {prior['yield_loss_pct']}%，建议 6 小时内启动滴灌。"
    )


def _level_cn(level: str) -> str:
    return {"critical": "重度", "warn": "中度", "normal": "轻度"}.get(level, "轻度")


def build_fallback_tree(context: dict, prior: dict, generated_at: str) -> dict:
    """降级路径：规则引擎产出与主模型**同结构**的推演树（V2_PLAN.md 第 7 节字段逐字一致）。"""
    metrics = context["metrics"]
    thresholds = context["thresholds"]
    soil_th = thresholds["soil_moisture"]
    temp_th = thresholds["temperature"]
    plot = context["plot"]

    soil = metrics.get("soil_moisture")
    temp = metrics.get("temperature")
    hum = metrics.get("humidity")
    # weather 表为空时 context_snapshot 返回 None：必须与 reasoning.py 一致地兜底，
    # 否则 dict.get(k, {}) 只在键缺失时生效、键存在值为 None 时仍返回 None。
    weather = context.get("weather") or {}

    root_severity = {"critical": "high", "warn": "warn", "normal": "good"}[prior["level"]]
    nodes: list[dict] = [
        {
            "id": "root",
            "type": "current",
            "level": 0,
            "label": "当前数据",
            "sub": f"墒情 {_num(soil, '%')} · 气温 {_num(temp, '℃')} · 湿度 {_num(hum, '%')}",
            "severity": root_severity,
        }
    ]
    links: list[dict] = []

    risk_index = 0
    if prior["yield_loss_pct"] > 0:
        risk_index += 1
        node_id = f"risk_{risk_index}"
        nodes.append({
            "id": node_id,
            "type": "risk",
            "level": 1,
            "parent": "root",
            "label": f"减产风险 {prior['yield_loss_pct']}%",
            "sub": f"缺水深度因子 {prior['depth_factor']} · 持续 {prior['hours_below_min']}h",
            "severity": "high" if prior["level"] == "critical" else "warn",
        })
        links.append({"source": "root", "target": node_id})
    else:
        risk_index += 1
        node_id = f"risk_{risk_index}"
        nodes.append({
            "id": node_id,
            "type": "risk",
            "level": 1,
            "parent": "root",
            "label": "减产风险 0%",
            "sub": f"墒情 {_num(soil, '%')} ≥ 正常下限 {soil_th['min']}%",
            "severity": "good",
        })
        links.append({"source": "root", "target": node_id})

    if temp is not None and temp > temp_th["max"]:
        risk_index += 1
        node_id = f"risk_{risk_index}"
        nodes.append({
            "id": node_id,
            "type": "risk",
            "level": 1,
            "parent": "root",
            "label": f"高温胁迫 {temp}℃",
            "sub": f"超过正常上限 {temp_th['max']}℃",
            "severity": "high" if temp > temp_th["critical_max"] else "warn",
        })
        links.append({"source": "root", "target": node_id})

    for index, plan in enumerate(prior["interventions"], start=1):
        node_id = f"plan_{index}"
        nodes.append({
            "id": node_id,
            "type": "plan",
            "level": 1,
            "parent": "root",
            "label": plan["label"],
            "sub": plan["sub"],
            "severity": "good",
            "command": {
                "action": plan["action"],
                "params": plan["params"],
                "device_code": plan["device_code"],
            },
            "effect": plan["effect"],
            "sku_keywords": plan["sku_keywords"],
        })
        links.append({"source": "root", "target": node_id})

    hit_rules = [r for r in prior["rules"] if r["hit"]]
    whitebox = [
        {
            "step": "环境数据读取",
            "detail": (
                f"读取 {plot.get('name')} 最近 {config.REASONING_WINDOW_MINUTES} 分钟遥测"
                f"（{len(context.get('window_samples') or [])} 条样本）："
                f"气温 {_num(temp, '℃')}、湿度 {_num(hum, '%')}、墒情 {_num(soil, '%')}、"
                f"土温 {_num(metrics.get('soil_temp'), '℃')}、电量 {_num(metrics.get('battery'), '%')}；"
                + (
                    f"气象：{weather.get('condition')} {weather.get('temperature')}℃ "
                    f"湿度 {weather.get('humidity')}% 降水 {weather.get('rainfall_mm')}mm "
                    f"{weather.get('wind_dir')}风 {weather.get('wind_level')} 级"
                    if weather
                    else "气象：暂无数据（模拟器尚未上报 agri/weather 主题）"
                )
            ),
            "ts": generated_at,
        },
        {
            "step": "匹配农学规则",
            "detail": (
                "；".join(f"{r['rule']} → {r['detail']}" for r in hit_rules)
                or "未命中任何胁迫规则"
            ),
            "ts": generated_at,
        },
        {
            "step": "大模型结论生成",
            "detail": (
                f"大模型不可用，已由本地农学先验规则引擎产出同结构结论："
                f"减产 {prior['yield_loss_pct']}%、耗电 {prior['power_kwh']} kWh"
            ),
            "ts": generated_at,
        },
    ]

    return {
        "tree": {"nodes": nodes, "links": links},
        "summary": summarize(context, prior),
        "yield_loss_pct": prior["yield_loss_pct"],
        "power_kwh": prior["power_kwh"],
        "whitebox": whitebox,
    }


def fallback_result(context: dict, prior: dict, generated_at: str, error: str | None) -> dict:
    """规则引擎的完整降级结果（与 reasoning.py 的主模型结果同结构）。"""
    built = build_fallback_tree(context, prior, generated_at)
    return {
        "source": "fallback",
        "model": "local-agronomy-rules",
        "degraded": True,
        "error": error,
        "prior_yield_loss_pct": prior["yield_loss_pct"],
        "prior_power_kwh": prior["power_kwh"],
        "corrected": False,
        "tree": built["tree"],
        "summary": built["summary"],
        "yield_loss_pct": built["yield_loss_pct"],
        "power_kwh": built["power_kwh"],
        "whitebox": built["whitebox"],
    }


def dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def now() -> str:
    return now_iso()
