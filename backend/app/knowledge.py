"""农学先验规则引擎（V2_PLAN.md 第 8.1 节最后一步、第 13 节第 5 条）。

**完全独立于大模型**：只用本地规则与配置口径算出结构化结论，
既用于降级路径（source=fallback 时的同结构 JSON），
也用于主模型路径的交叉校验（偏差 >15 个百分点即以后端先验为准）。

口径（冻结，答辩口径）：
- V2.1 C-6：灌溉按**水量平衡**算，不拍脑袋。根层湿润区亏缺水量
  water_m3 = area_mu × 666.7 × (target% - current%)/100 × (root_depth_cm/100) × wetted_ratio；
  系统流量 drip_flow_m3_per_h = area_mu × drip_emitter_lph × (666.7/(drip_spacing_m × row_spacing_m))/1000；
  时长由水量反推 duration_min = water_m3 / flow × 60，耗电 power_kwh = water_m3 × KWH_PER_M3（0.15 kWh/m³）。
  单次时长上限 IRRIGATION_MAX_MINUTES，超限按上限执行并在方案里写明本次只覆盖亏缺的比例。
- V2.1 C-11：水分胁迫减产**连续化**——severity = depth^1.5 × duration_factor，
  loss = YIELD_LOSS_MAX_PCT × severity，无 15% 下限；墒情达正常下限即 0。
  持续时间因子分母 72h（24h 窗口下恒为 0，是 C-11 要修的旧 bug）。
- V2.1 C-11：墒情阈值按 soil_texture 分档，由 config.meta_thresholds(plot) 传入。
- V2.1 C-8：墒情/土温只取本地块 type=="soil" 设备，气温/湿度/CO2 只取 type=="env" 设备，
  绝不把两台设备样本混算；本地块无墒情站时**不回落别的地块**，改为明说无法下发灌溉指令。
- V2.1 C-11：露天高温不适用通风降温（改滴灌降温 / 树盘覆盖），只有温室才出 ventilation_on；
  高湿不再直接推「施药 60ml」，改为炭疽病风险提示 + 48h 内喷施保护性杀菌剂（剂量按标签/农技员确认）。

本模块**不访问网络、不访问数据库**，纯函数，便于单测与答辩讲解。
"""
from __future__ import annotations

import json

from . import config
from .timeutil import now_iso

# 根层湿润区换算系数：1 亩 = 666.7 m²
MU_TO_M2 = 666.7


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
    """持续时间因子：0h→0，≥72h→1，中间线性（V2.1 C-11：分母 24→72）。"""
    return _clamp(hours_below_min / 72.0, 0.0, 1.0)


def _depth_factor(soil_moisture: float, soil_threshold: dict) -> float:
    """缺水深度因子：达到正常下限→0，跌到 critical_min 及以下→1。"""
    low = _f(soil_threshold.get("min"), 35.0)
    critical = _f(soil_threshold.get("critical_min"), 25.0)
    span = max(low - critical, 0.001)
    return _clamp((low - soil_moisture) / span, 0.0, 1.0)


# ---------------- 灌溉水量平衡（V2.1 C-6） ----------------
def drip_flow_m3_per_h(plot: dict) -> float:
    """地块滴灌系统流量（m³/h）：按亩均滴头数与单滴头流量换算。"""
    area_mu = _f(plot.get("area_mu"), 0.0)
    emitter_lph = _f(plot.get("drip_emitter_lph"), 2.0)
    drip_spacing = max(_f(plot.get("drip_spacing_m"), 0.30), 0.001)
    row_spacing = max(_f(plot.get("row_spacing_m"), 4.0), 0.001)
    emitters_per_mu = MU_TO_M2 / (drip_spacing * row_spacing)
    return area_mu * emitter_lph * emitters_per_mu / 1000.0


def root_zone_deficit_m3(plot: dict, soil_pct: float, target_pct: float) -> float:
    """根层湿润区亏缺水量（m³）。"""
    area_mu = _f(plot.get("area_mu"), 0.0)
    root_depth_m = _f(plot.get("root_depth_cm"), 40.0) / 100.0
    wetted_ratio = _f(plot.get("wetted_ratio"), 0.30)
    delta_pct = max(_f(target_pct) - _f(soil_pct), 0.0)
    return area_mu * MU_TO_M2 * (delta_pct / 100.0) * root_depth_m * wetted_ratio


def power_kwh_for_duration(plot: dict, duration_min: float) -> float:
    """给定灌溉时长对应的耗电（kWh）——与时长严格成正比（V2.1 C-6）。"""
    water_m3 = drip_flow_m3_per_h(plot) * _f(duration_min) / 60.0
    return water_m3 * config.KWH_PER_M3


def irrigation_plan(plot: dict, soil_pct: float, thresholds: dict) -> dict:
    """由墒情亏缺反推灌溉方案：目标墒情取该地块正常区间中点。"""
    soil_th = thresholds["soil_moisture"]
    target = (soil_th["min"] + soil_th["max"]) / 2.0
    flow = drip_flow_m3_per_h(plot)
    water = root_zone_deficit_m3(plot, soil_pct, target)
    raw_minutes = (water / flow * 60.0) if flow > 0 else 0.0
    duration = int(round(raw_minutes))
    capped = duration > config.IRRIGATION_MAX_MINUTES
    duration = min(max(duration, 0), config.IRRIGATION_MAX_MINUTES)
    delivered = flow * duration / 60.0
    coverage = (delivered / water * 100.0) if water > 0 else 100.0
    return {
        "target_pct": round(target, 1),
        "flow_m3_per_h": round(flow, 2),
        "water_m3": round(water, 1),
        "duration_min": duration,
        "capped": capped,
        "coverage_pct": round(_clamp(coverage, 0.0, 100.0), 1),
        "power_kwh": round(delivered * config.KWH_PER_M3, 1),
    }


# ---------------- 设备按类型/地块绑定（V2.1 C-8） ----------------
def _device_meta(code: str, context: dict) -> dict:
    for item in context.get("devices") or []:
        if item.get("device_code") == code:
            return item
    return config.DEVICE_BY_CODE.get(code) or {}


def _pick_device(plot: dict, context: dict, device_type: str) -> str | None:
    """按「本地块 + 设备类型」挑设备；找不到返回 None，绝不回落到别的地块。"""
    plot_code = (plot or {}).get("plot_code")
    if not plot_code:
        return None
    for code in context.get("device_codes") or []:
        if _device_meta(code, context).get("type") == device_type:
            return code
    for meta in config.DEVICES:
        if meta.get("plot_code") == plot_code and meta.get("type") == device_type:
            return meta["device_code"]
    return None


def _soil_device(plot: dict, context: dict) -> str | None:
    """本地块的墒情站（type=="soil"）。"""
    return _pick_device(plot, context, "soil")


def _env_device(plot: dict, context: dict) -> str | None:
    """本地块的环境站（type=="env"）。"""
    return _pick_device(plot, context, "env")


def metric_sources(plot: dict, context: dict) -> dict:
    """每个指标的具体来源设备码与安装说明（V2.1 C-8 白盒第一步必须写清）。"""
    sources: dict = {}
    for metric in ("temperature", "humidity", "co2"):
        code = _env_device(plot, context)
        if code:
            sources[metric] = {"device_code": code, "install_note": _device_meta(code, context).get("install_note", "")}
    for metric in ("soil_moisture", "soil_temp"):
        code = _soil_device(plot, context)
        if code:
            sources[metric] = {"device_code": code, "install_note": _device_meta(code, context).get("install_note", "")}
    return sources


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
    greenhouse = plot.get("scenario") == "greenhouse"

    soil_th = thresholds["soil_moisture"]
    temp_th = thresholds["temperature"]
    hum_th = thresholds["humidity"]

    rules: list[dict] = []

    # 规则 1：水分胁迫（连续函数，无 15% 下限）
    depth = _depth_factor(soil, soil_th) if soil is not None else 0.0
    dur = _duration_factor(hours_below)
    if soil is None:
        rules.append({"rule": "土壤墒情 < 正常下限 → 减产（连续函数）", "hit": False,
                      "detail": "本窗口无墒情采样，无法判定"})
    elif soil >= soil_th["min"]:
        rules.append({"rule": "土壤墒情 < 正常下限 → 减产（连续函数）", "hit": False,
                      "detail": f"墒情 {soil}% ≥ 正常下限 {soil_th['min']}%，无水分胁迫"})
    else:
        loss = config.YIELD_LOSS_MAX_PCT * (depth ** 1.5) * dur
        rules.append({
            "rule": "土壤墒情 < 正常下限 → 减产（连续函数）",
            "hit": True,
            "detail": (
                f"墒情 {soil}% < 正常下限 {soil_th['min']}%；缺水深度因子 {depth:.2f}"
                f"（临界 {soil_th['critical_min']}%），持续 {hours_below:.1f}h，"
                f"持续时间因子 {dur:.2f}（分母 72h）→ 减产 {loss:.1f}%"
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

    # 规则 3：高湿病害风险（露天与温室给不同降湿路径）
    if humidity is None:
        rules.append({"rule": "空气湿度 > 上限 → 炭疽/溃疡风险", "hit": False, "detail": "无湿度采样"})
    elif humidity > hum_th["max"]:
        advice = "建议通风降湿并控温" if greenhouse else "建议雨前保护性用药、避免树冠长时间结露"
        rules.append({"rule": "空气湿度 > 上限 → 炭疽/溃疡风险", "hit": True,
                      "detail": f"湿度 {humidity}% > 正常上限 {hum_th['max']}%，{advice}"})
    else:
        rules.append({"rule": "空气湿度 > 上限 → 炭疽/溃疡风险", "hit": False,
                      "detail": f"湿度 {humidity}% 未超上限 {hum_th['max']}%"})

    # 规则 4：灌溉耗电口径（V2.1 C-6：按 m³ 计，不再按亩均拍脑袋）
    rules.append({
        "rule": f"灌溉耗电 {config.KWH_PER_M3} kWh/m³（低扬程滴灌 0.12~0.18）",
        "hit": True,
        "detail": (
            f"地块 {plot.get('name')} 面积 {area_mu} 亩，系统流量 {drip_flow_m3_per_h(plot):.2f} m³/h，"
            f"耗电 = 实际灌水量(m³) × {config.KWH_PER_M3} kWh/m³"
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

    # V2.1 C-11：连续化减产率——severity = depth^1.5 × duration_factor，无 15% 下限。
    if soil is not None and soil < soil_th["min"]:
        severity = (depth ** 1.5) * dur
        yield_loss = config.YIELD_LOSS_MAX_PCT * severity
    else:
        severity = 0.0
        yield_loss = 0.0
    yield_loss = round(_clamp(yield_loss, 0.0, 100.0), 1)

    # V2.1 C-6：耗电来自水量平衡（无灌溉需求则 0）。
    irrigation = None
    if soil is not None and soil < soil_th["min"] and drip_flow_m3_per_h(plot) > 0:
        irrigation = irrigation_plan(plot, soil, thresholds)
        power_kwh = irrigation["power_kwh"]
    else:
        power_kwh = 0.0

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
        "severity": round(severity, 4),
        "level": level,
        "depth_factor": round(depth, 3),
        "duration_factor": round(dur, 3),
        "hours_below_min": round(hours_below, 2),
        "irrigation": irrigation,
        "rules": rules,
        "interventions": interventions,
    }


def _no_soil_node(plot: dict, soil, soil_th: dict) -> dict:
    """V2.1 C-8/C-11：本地块没有 type=soil 的墒情站时，明说下发不了灌溉指令。

    绝不借别的地块的设备"假装能灌"；本节点 action 为 None，前端不会生成可下发指令。
    """
    if soil is None:
        sub = "本窗口无墒情采样，且本地块未配置 type=soil 的墒情设备，请先补装土壤墒情探头（20cm 埋深）"
    else:
        sub = f"墒情 {soil}% 低于正常下限 {soil_th['min']}%，请先补装土壤墒情探头（20cm 埋深）"
    return {
        "action": None,
        "params": {},
        "device_code": None,
        "label": "本地块无墒情站，无法下发灌溉指令",
        "sub": sub,
        "effect": {"soil_moisture_delta": 0.0, "yield_recover_pct": 0.0},
        "sku_keywords": ["土壤墒情探头"],
        "reason": f"{plot.get('name')} 未配置 type=soil 的墒情设备，灌溉决策缺少实测依据",
    }


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
    greenhouse = plot.get("scenario") == "greenhouse"
    soil_device = _soil_device(plot, context)
    env_device = _env_device(plot, context)

    plans: list[dict] = []

    if soil is not None and soil < soil_th["min"]:
        if soil_device is None and not greenhouse:
            # V2.1 C-11/C-8：本地块没有墒情站，就明说下发不了，绝不借别的地块的设备。
            plans.append(_no_soil_node(plot, soil, soil_th))
        else:
            plan = irrigation_plan(plot, soil, thresholds)
            duration_min = plan["duration_min"]
            delta = round(min(plan["coverage_pct"] / 100.0 * (plan["target_pct"] - soil), 100.0), 1)
            if plan["capped"]:
                sub = (
                    f"单次上限 {config.IRRIGATION_MAX_MINUTES} 分钟，本次仅覆盖亏缺的 "
                    f"{plan['coverage_pct']}%，剩余需下一次灌溉 · 耗电 {plan['power_kwh']} 度"
                )
            else:
                sub = (
                    f"灌水量 {plan['water_m3']} m³（系统流量 {plan['flow_m3_per_h']} m³/h）"
                    f"· 耗电 {plan['power_kwh']} 度 · 墒情回升 {delta}%"
                )
            plans.append({
                "action": "irrigation_on",
                "params": {"duration_min": duration_min},
                "device_code": soil_device,
                "label": f"开启滴灌 {duration_min} 分钟",
                "sub": sub,
                "effect": {
                    "soil_moisture_delta": delta,
                    "yield_recover_pct": round(min(14.0, delta * 0.8), 1),
                },
                "sku_keywords": ["滴灌带", "抗旱保水剂"],
                "reason": (
                    f"墒情 {soil}% 低于正常下限 {soil_th['min']}%（{plot.get('soil_texture', '壤土')}），"
                    f"按水量平衡灌至区间中位 {plan['target_pct']}%：根层 {plot.get('root_depth_cm')}cm × "
                    f"湿润比 {plot.get('wetted_ratio')} × {area_mu} 亩 → {plan['water_m3']} m³，"
                    f"÷ {plan['flow_m3_per_h']} m³/h → {duration_min} 分钟"
                ),
            })

    elif soil_device is None and not greenhouse:
        # V2.1 C-8/C-11：本地块连墒情采样都没有，同样明说下发不了，不借别的地块设备。
        plans.append(_no_soil_node(plot, soil, soil_th))

    if temp is not None and temp > temp_th["max"]:
        if greenhouse:
            plans.append({
                "action": "ventilation_on",
                "params": {"duration_min": 20},
                "device_code": env_device,
                "label": "开启通风降温 20 分钟",
                "sub": "预计棚内降温 2~3℃ · 抑制高温逼熟",
                "effect": {"soil_moisture_delta": 0.0, "yield_recover_pct": 2.0},
                "sku_keywords": ["滴灌带"],
                "reason": f"棚内气温 {temp}℃ 高于正常上限 {temp_th['max']}℃，温室可开启通风降温",
            })
        else:
            plans.append({
                "action": "irrigation_on",
                "params": {"duration_min": 30},
                "device_code": soil_device,
                "label": "滴灌降温 / 树盘覆盖",
                "sub": f"预计冠层降温 2~3℃ · 日灼风险下降（露天园区无降温设施）",
                "effect": {"soil_moisture_delta": 0.0, "yield_recover_pct": 2.0},
                "sku_keywords": ["滴灌带"],
                "reason": (
                    f"气温 {temp}℃ 高于正常上限 {temp_th['max']}℃；露天地块以滴灌降温与树盘覆盖"
                    f"降低地表与冠层温度"
                ),
            })

    if humidity is not None and humidity > hum_th["max"]:
        plans.append({
            "action": "pesticide_dose",
            "params": {
                "target": "炭疽病风险提示",
                "window_hours": 48,
                "note": "具体药剂与剂量按标签/农技员确认",
            },
            "device_code": env_device,
            "label": "炭疽病风险提示",
            "sub": "建议 48h 内喷施保护性杀菌剂，具体药剂与剂量按标签/农技员确认",
            "effect": {"soil_moisture_delta": 0.0, "yield_recover_pct": 3.0},
            "sku_keywords": ["杀菌剂", "代森锰锌", "咪鲜胺"],
            "reason": f"湿度 {humidity}% 高于正常上限 {hum_th['max']}%，炭疽病流行风险上升",
        })

    if not plans and greenhouse and env_device is not None:
        # 温室菇棚兜底：棚内不做墒情灌溉决策，改为一次常规通风换气（避免 C 区方案区空白）。
        plans.append({
            "action": "ventilation_on",
            "params": {"duration_min": 15},
            "device_code": env_device,
            "label": "通风换气 15 分钟",
            "sub": "维持棚内温湿度与 CO₂ 在适宜区间",
            "effect": {"soil_moisture_delta": 0.0, "yield_recover_pct": 0.0},
            "sku_keywords": [],
            "reason": f"{plot.get('name')} 当前无越界指标，按温室常规管理做一次通风换气",
        })
    elif not plans and soil_device is not None:
        # 数据正常时也给一条保守可执行项，保证前端绿色节点不空（口径不变）。
        plans.append({
            "action": "irrigation_on",
            "params": {"duration_min": 15},
            "device_code": soil_device,
            "label": "预防性滴灌 15 分钟",
            "sub": f"维持墒情在 {soil_th['min']:.0f}~{soil_th['max']:.0f}% 区间",
            "effect": {
                "soil_moisture_delta": round(
                    (drip_flow_m3_per_h(plot) * 0.25) / (area_mu * MU_TO_M2 * _f(plot.get("root_depth_cm"), 40.0) / 100.0 * _f(plot.get("wetted_ratio"), 0.3)) * 100.0,
                    1,
                ) if drip_flow_m3_per_h(plot) > 0 else 0.0,
                "yield_recover_pct": 0.0,
            },
            "sku_keywords": ["滴灌带"],
            "reason": f"当前各项指标正常，按 {area_mu} 亩面积做一次预防性小水勤灌",
        })

    return plans[:3]


def summarize(context: dict, prior: dict) -> str:
    plot = context["plot"]
    metrics = context["metrics"]
    greenhouse = plot.get("scenario") == "greenhouse"
    crop = plot.get("crop") or "作物"
    if prior["yield_loss_pct"] <= 0:
        if greenhouse:
            # V2.1 C-11：温室菇棚无墒情站，结论里不得出现"墒情"字样，改报棚内气温/湿度/CO₂。
            return (
                f"{plot.get('name')}（{crop}）当前棚内气温 {_num(metrics.get('temperature'), '℃')}、"
                f"空气湿度 {_num(metrics.get('humidity'), '%')}、"
                f"CO₂ {_num(metrics.get('co2'), 'ppm')}，各项指标处于正常区间，暂无减产风险。"
            )
        return (
            f"{plot.get('name')}（{crop}）当前墒情 {_num(metrics.get('soil_moisture'), '%')}、"
            f"气温 {_num(metrics.get('temperature'), '℃')}，各项指标处于正常区间，暂无减产风险。"
        )
    if greenhouse:
        return (
            f"{plot.get('name')}（{crop}）处于{_level_cn(prior['level'])}环境胁迫，"
            f"预计减产 {prior['yield_loss_pct']}%，建议优先通风控温控湿。"
        )
    return (
        f"{plot.get('name')}（{crop}）处于{_level_cn(prior['level'])}水分胁迫，"
        f"预计减产 {prior['yield_loss_pct']}%，建议 6 小时内启动滴灌。"
    )


def _level_cn(level: str) -> str:
    return {"critical": "重度", "warn": "中度", "normal": "轻度"}.get(level, "轻度")


def _source_text(plot: dict, context: dict, metric: str, fallback: str) -> str:
    sources = context.get("metric_sources") or metric_sources(plot, context)
    entry = sources.get(metric)
    if not entry:
        return fallback
    note = entry.get("install_note") or ""
    return f"来自 {entry.get('device_code')}" + (f"（{note}）" if note else "")


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

    greenhouse = plot.get("scenario") == "greenhouse"
    root_severity = {"critical": "high", "warn": "warn", "normal": "good"}[prior["level"]]
    # V2.1 C-11：温室菇棚没有墒情站，当前数据节点改报棚内气温/湿度/CO₂，不得出现"墒情"。
    root_sub = (
        f"棚内气温 {_num(temp, '℃')} · 湿度 {_num(hum, '%')} · CO₂ {_num(metrics.get('co2'), 'ppm')}"
        if greenhouse
        else f"墒情 {_num(soil, '%')} · 气温 {_num(temp, '℃')} · 湿度 {_num(hum, '%')}"
    )
    nodes: list[dict] = [
        {
            "id": "root",
            "type": "current",
            "level": 0,
            "label": "当前数据",
            "sub": root_sub,
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
            "sub": (
                f"棚内气温 {_num(temp, '℃')} · 湿度 {_num(hum, '%')} 均在正常区间"
                if greenhouse
                else f"墒情 {_num(soil, '%')} ≥ 正常下限 {soil_th['min']}%"
            ),
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
        node: dict = {
            "id": node_id,
            "type": "plan",
            "level": 1,
            "parent": "root",
            "label": plan["label"],
            "sub": plan["sub"],
            "severity": "good",
            "effect": plan["effect"],
            "sku_keywords": plan["sku_keywords"],
        }
        # V2.1 C-11：没有可执行动作（例如本地块无墒情站）时不产生 command 节点。
        if plan.get("action") and plan.get("device_code"):
            node["command"] = {
                "action": plan["action"],
                "params": plan["params"],
                "device_code": plan["device_code"],
            }
        nodes.append(node)
        links.append({"source": "root", "target": node_id})

    hit_rules = [r for r in prior["rules"] if r["hit"]]
    soil_source = _source_text(plot, context, "soil_moisture", "本地块无墒情站")
    temp_source = _source_text(plot, context, "temperature", "本地块无环境站")
    hum_source = _source_text(plot, context, "humidity", "本地块无环境站")
    irrigation = prior.get("irrigation") or {}
    water_text = (
        f"水量平衡：亏缺 {irrigation.get('water_m3')} m³ ÷ 系统流量 "
        f"{irrigation.get('flow_m3_per_h')} m³/h → {irrigation.get('duration_min')} 分钟，"
        f"耗电 {irrigation.get('power_kwh')} kWh（{config.KWH_PER_M3} kWh/m³）；"
        if irrigation
        else ""
    )
    if greenhouse:
        # V2.1 C-11：温室菇棚没有墒情站，读取明细只报环境站（含 CO₂），不得出现墒情/土温。
        readings = (
            f"气温 {_num(temp, '℃')}（{temp_source}）、湿度 {_num(hum, '%')}（{hum_source}）、"
            f"CO₂ {_num(metrics.get('co2'), 'ppm')}（{temp_source}）、"
            f"电量 {_num(metrics.get('battery'), '%')}；"
        )
    else:
        readings = (
            f"气温 {_num(temp, '℃')}（{temp_source}）、湿度 {_num(hum, '%')}（{hum_source}）、"
            f"墒情 {_num(soil, '%')}（{soil_source}）、"
            f"土温 {_num(metrics.get('soil_temp'), '℃')}（{soil_source}）、"
            f"电量 {_num(metrics.get('battery'), '%')}；"
        )
    whitebox = [
        {
            "step": "环境数据读取",
            "detail": (
                f"读取 {plot.get('name')} 最近 {config.REASONING_WINDOW_MINUTES} 分钟遥测"
                f"（{len(context.get('window_samples') or [])} 条样本）："
                + readings
                + water_text
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
