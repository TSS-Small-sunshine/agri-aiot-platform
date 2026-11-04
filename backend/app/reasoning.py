"""Context Engineering 推演（V2_PLAN.md 第 8 节）。

流水线（§8.1）：
  plot_code
    → 地块元数据（config.PLOTS）
    → 最近 10 分钟遥测（均值 + 最新值 + 极值）
    → 最新气象 + 未来 24h 模拟预报（weather 表）
    → 阈值快照（config.THRESHOLDS，与 /api/meta 同源）
    → 农学先验模型独立计算（knowledge.py，不依赖大模型）
    → 渲染中文上下文块 → 拼 System + Schema → 调 LLM → pydantic 校验 → 回填交叉校验结果

三段式降级（§8.4）：
  1. 合法 JSON → source=primary
  2. 数字与先验偏差 >15 个百分点 → 以后端先验为准，corrected=true，白盒写明「已用农学先验模型校正」
  3. 无 Key / 超时 / 非 JSON / Schema 失败 → knowledge.py 产出同结构 JSON，source=fallback

铁律：任何异常都收敛为降级结果，**绝不冒泡成 5xx**。
"""
from __future__ import annotations

import json
import logging
import time
import uuid

from pydantic import ValidationError

from . import config, db, knowledge, llm, schemas, weather as weather_mod
from .timeutil import now_iso, parse_iso

log = logging.getLogger("agri.reasoning")

# System Prompt —— V2_PLAN.md §8.2 原文，逐字照抄。
SYSTEM_PROMPT = """你是资深柑橘栽培与农业物联网决策专家。你会收到某地块的实时传感、气象与阈值数据。
你的任务是基于这些数据做胁迫诊断与干预推演。
硬性要求：
1. 只输出一个 JSON 对象，不要 Markdown 代码块、不要任何解释文字；
2. 减产率与耗电量必须是数字，且必须由你基于上下文推理得出，不得照抄输入；
3. 干预策略 2~3 条，每条必须可执行、有量化收益；
4. 严格遵循给定 JSON Schema。"""

# 输出 JSON Schema（内联进 User Prompt，§8.3 末尾的 {inline_schema}）
INLINE_SCHEMA = {
    "type": "object",
    "required": ["summary", "yield_loss_pct", "power_kwh", "tree", "whitebox"],
    "properties": {
        "summary": {"type": "string", "description": "一句话结论，含地块名与建议动作"},
        "yield_loss_pct": {"type": "number", "description": "减产风险百分比，0~100"},
        "power_kwh": {"type": "number", "description": "本次干预预计耗电量 kWh"},
        "tree": {
            "type": "object",
            "required": ["nodes", "links"],
            "properties": {
                "nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "type", "level", "label", "sub", "severity"],
                        "properties": {
                            "id": {"type": "string"},
                            "type": {"type": "string", "enum": ["current", "risk", "plan"]},
                            "level": {"type": "integer"},
                            "parent": {"type": "string"},
                            "label": {"type": "string"},
                            "sub": {"type": "string"},
                            "severity": {"type": "string", "enum": ["good", "warn", "high"]},
                            "command": {
                                "type": "object",
                                "properties": {
                                    "action": {"type": "string"},
                                    "params": {"type": "object"},
                                    "device_code": {"type": "string"},
                                },
                            },
                            "effect": {
                                "type": "object",
                                "properties": {
                                    "soil_moisture_delta": {"type": "number"},
                                    "yield_recover_pct": {"type": "number"},
                                },
                            },
                            "sku_keywords": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "links": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["source", "target"],
                        "properties": {
                            "source": {"type": "string"},
                            "target": {"type": "string"},
                        },
                    },
                },
            },
        },
        "whitebox": {
            "type": "array",
            "minItems": 3,
            "items": {
                "type": "object",
                "required": ["step", "detail"],
                "properties": {
                    "step": {"type": "string"},
                    "detail": {"type": "string"},
                    "ts": {"type": "string"},
                },
            },
        },
    },
}


# ---------------- 上下文组装 ----------------
def _round(value, digits: int = 1):
    return None if value is None else round(float(value), digits)


def _num(value, unit: str = "") -> str:
    """诚实渲染：无采样时显示「暂无数据」，绝不显示字面 None。"""
    return "暂无数据" if value is None else f"{value}{unit}"


def _stats(rows: list[dict], key: str) -> dict:
    values = [float(r[key]) for r in rows if r.get(key) is not None]
    if not values:
        return {"avg": None, "min": None, "max": None, "latest": None, "count": 0}
    return {
        "avg": round(sum(values) / len(values), 1),
        "min": round(min(values), 1),
        "max": round(max(values), 1),
        "latest": round(values[-1], 1),
        "count": len(values),
    }


def _hours_below_min(device_codes: list[str], min_value: float, hours: int = 72) -> float:
    """墒情连续低于正常下限的持续小时数（从最近一次采样往回找第一个达标点）。

    数据不足时按窗口内低于下限的样本跨度估算，避免"数据少就报 0 小时"。
    """
    from .timeutil import cutoff_iso

    cutoff = cutoff_iso(hours)
    rows = db.query(
        """SELECT device_code, ts, soil_moisture FROM telemetry
           WHERE device_code IN (%s) AND ts >= ? AND soil_moisture IS NOT NULL
           ORDER BY ts ASC, id ASC"""
        % ",".join("?" for _ in device_codes),
        tuple(device_codes) + (cutoff,),
    )
    if not rows:
        return 0.0

    # 按设备分组，取每台设备"最近连续低于下限"的起点，再取最早的那个。
    spans: list[float] = []
    for code in device_codes:
        series = [r for r in rows if r["device_code"] == code]
        if not series:
            continue
        if series[-1]["soil_moisture"] >= min_value:
            continue
        start_index = len(series) - 1
        while start_index > 0 and series[start_index - 1]["soil_moisture"] < min_value:
            start_index -= 1
        begin = parse_iso(series[start_index]["ts"])
        end = parse_iso(series[-1]["ts"])
        if begin and end:
            spans.append(max((end - begin).total_seconds() / 3600.0, 0.0))
    return round(max(spans), 2) if spans else 0.0


def build_context(plot_code: str) -> dict | None:
    """按 §8.1 组装上下文（全部来自真实库表与配置，无编造值）；未知地块返回 None。"""
    from .timeutil import cutoff_iso

    # V2.1 C-9：未知地块不再编造默认地块，直接返回 None，由路由层给出 404。
    plot_meta = config.plot_meta(plot_code)
    if plot_meta is None:
        return None
    device_codes = [d["device_code"] for d in config.DEVICES if d["plot_code"] == plot_code]
    if not device_codes:
        device_codes = [d["device_code"] for d in db.list_devices() if d["plot_code"] == plot_code]

    window = cutoff_iso(config.REASONING_WINDOW_MINUTES / 60.0)
    window_rows = (
        db.query(
            """SELECT device_code, ts, temperature, humidity, soil_moisture, soil_temp, battery
               FROM telemetry WHERE device_code IN (%s) AND ts >= ?
               ORDER BY ts ASC, id ASC"""
            % ",".join("?" for _ in device_codes),
            tuple(device_codes) + (window,),
        )
        if device_codes
        else []
    )

    # V2.1 C-8：指标按设备类型绑定——墒情/土温只取 type=="soil"，气温/湿度只取 type=="env"。
    devices = [
        {
            "device_code": d["device_code"],
            "type": d.get("type"),
            "install_note": d.get("install_note", ""),
        }
        for d in config.DEVICES
        if d["plot_code"] == plot_code
    ] or [
        {"device_code": d["device_code"], "type": d["type"], "install_note": ""}
        for d in db.list_devices()
        if d["plot_code"] == plot_code
    ]
    type_by_code = {d["device_code"]: d.get("type") for d in devices}

    def rows_of(device_type: str) -> list[dict]:
        return [r for r in window_rows if type_by_code.get(r["device_code"]) == device_type]

    env_rows = rows_of("env")
    soil_rows = rows_of("soil")

    # 温室环境站额外上报 CO2；露天地块没有这一路数据。
    metric_groups = {
        "temperature": env_rows,
        "humidity": env_rows,
        "co2": env_rows,
        "soil_moisture": soil_rows,
        "soil_temp": soil_rows,
        "battery": window_rows,
    }
    metric_keys = (
        ("temperature", "humidity", "soil_moisture", "soil_temp", "battery")
        + (("co2",) if plot_meta.get("scenario") == "greenhouse" else ())
    )

    stats_by_metric = {key: _stats(metric_groups.get(key, []), key) for key in metric_keys}
    metrics: dict = {key: stats_by_metric[key]["latest"] for key in metric_keys}
    # battery 取本窗口所有设备的平均值（电量是设备自身状态，不属于任何一类指标）。
    metrics["battery"] = _stats(window_rows, "battery")["latest"]

    # 气象：优先用 weather.context_snapshot 归一化后的字段名（与 §7 冻结结构一致）
    weather = weather_mod.context_snapshot(plot_code)

    soil_thresholds = config.soil_thresholds_for(plot_meta)
    context = {
        "plot": {
            "plot_code": plot_meta["plot_code"],
            "plot_name": plot_meta["plot_name"],
            "name": plot_meta.get("name") or plot_meta["plot_name"],
            "crop": plot_meta.get("crop", "柑橘"),
            "area_mu": plot_meta.get("area_mu", 10.0),
            "stage": plot_meta.get("stage", ""),
            "col": plot_meta.get("col", 0),
            "row": plot_meta.get("row", 0),
            "scenario": plot_meta.get("scenario", "open_field"),
            "soil_texture": plot_meta.get("soil_texture"),
        },
        "metrics": metrics,
        "metrics_stats": stats_by_metric,
        "weather": weather,
        "thresholds": config.meta_thresholds(plot_meta),
        "device_codes": device_codes,
        "devices": devices,
        "window_samples": window_rows,
        "window_minutes": config.REASONING_WINDOW_MINUTES,
        "hours_below_min": _hours_below_min(device_codes, float(soil_thresholds["min"]))
        if device_codes
        else 0.0,
    }
    context["metric_sources"] = knowledge.metric_sources(context["plot"], context)
    return context


# ---------------- Prompt 渲染（§8.3 原文模板） ----------------
def render_user_prompt(context: dict, prior: dict) -> str:
    plot = context["plot"]
    m = context["metrics"]
    w = context.get("weather") or {}
    t = context["thresholds"]["temperature"]
    h = context["thresholds"]["humidity"]
    s = context["thresholds"]["soil_moisture"]

    def num(value, unit: str = "") -> str:
        return "暂无数据" if value is None else f"{value}{unit}"

    weather_line = (
        "暂无气象数据（模拟器尚未上报 agri/weather 主题）"
        if not w
        else (
            f"气温 {w.get('temperature')}℃｜湿度 {w.get('humidity')}%｜"
            f"降水 {w.get('rainfall_mm')}mm｜{w.get('wind_dir')}风 {w.get('wind_level')} 级｜"
            f"{w.get('condition')}"
        )
    )

    sources = context.get("metric_sources") or {}

    def src(metric: str) -> str:
        entry = sources.get(metric) or {}
        if not entry:
            return "无对应设备"
        note = entry.get("install_note") or ""
        return f"{entry.get('device_code')}" + (f"（{note}）" if note else "")

    scenario_cn = "温室" if plot.get("scenario") == "greenhouse" else "露天"
    irrigation = prior.get("irrigation") or {}
    if irrigation:
        water_line = (
            f"水量平衡：根层亏缺 {irrigation.get('water_m3')} m³ ÷ 系统流量 "
            f"{irrigation.get('flow_m3_per_h')} m³/h → {irrigation.get('duration_min')} 分钟；"
            f"耗电 {irrigation.get('power_kwh')} kWh（{config.KWH_PER_M3} kWh/m³）"
        )
    else:
        water_line = "水量平衡：当前无灌溉需求（墒情未低于正常下限）"

    co2_line = ""
    if plot.get("scenario") == "greenhouse":
        co2_line = f"\n棚内 CO₂ {num(m.get('co2'), 'ppm')}（{src('co2')}）"

    body = f"""【地块】{plot['name']}｜作物 {plot['crop']}｜面积 {plot['area_mu']} 亩｜物候期 {plot['stage']}｜场景 {scenario_cn}｜土壤质地 {plot.get('soil_texture') or '壤土'}
【实时传感（最近 {context['window_minutes']} 分钟）】
空气温度 {num(m.get('temperature'), '℃')}（{src('temperature')}；正常 {t['min']}~{t['max']}，critical >{t['critical_max']}）
空气湿度 {num(m.get('humidity'), '%')}（{src('humidity')}；正常 {h['min']}~{h['max']}，critical >{h['critical_max']} 或 <{h['critical_min']}）
土壤墒情 {num(m.get('soil_moisture'), '%')}（{src('soil_moisture')}；正常 {s['min']}~{s['max']}，critical <{s['critical_min']}）
土壤温度 {num(m.get('soil_temp'), '℃')}（{src('soil_temp')}）｜设备电量 {num(m.get('battery'), '%')}{co2_line}
【气象（未来 24h 模拟预报）】
{weather_line}
【后端农学先验模型参考（独立算出，仅供交叉校验，你可以不同意并给出你的判断）】
水分胁迫减产估计 {prior['yield_loss_pct']}%｜{water_line}
【任务】判断胁迫等级；给出减产风险百分比（整数 0~100）；给出 2~3 条干预策略及预计耗电与墒情回升；
如涉及植保用药给出药品关键词；输出 3 步白盒推演过程。
【输出 JSON Schema】{json.dumps(INLINE_SCHEMA, ensure_ascii=False)}"""
    return body


def build_prompt(context: dict, prior: dict) -> str:
    """完整 Prompt 原文（System + User），供白盒回看；超过 8KB 截断。"""
    text = f"===== SYSTEM =====\n{SYSTEM_PROMPT}\n\n===== USER =====\n{render_user_prompt(context, prior)}"
    raw = text.encode("utf-8")
    if len(raw) > config.PROMPT_MAX_BYTES:
        truncated = raw[: config.PROMPT_MAX_BYTES].decode("utf-8", errors="ignore")
        text = truncated + "\n…（prompt 已截断至 8KB）"
    return text


# ---------------- 交叉校验（§8.4 第二段） ----------------
def cross_check(payload: dict, prior: dict) -> tuple[dict, bool, str | None]:
    """返回 (最终 payload, 是否已校正, 校正说明)。偏差 >15 个百分点即以后端先验为准。"""
    model_loss = float(payload["yield_loss_pct"])
    prior_loss = float(prior["yield_loss_pct"])
    deviation = abs(model_loss - prior_loss)
    if deviation <= config.REASONING_PRIOR_TOLERANCE_PCT:
        return payload, False, None

    payload["yield_loss_pct"] = prior_loss
    payload["power_kwh"] = prior["power_kwh"]
    note = (
        f"大模型给出减产 {model_loss}%，与农学先验模型 {prior_loss}% 偏差 "
        f"{deviation:.1f} 个百分点（>{config.REASONING_PRIOR_TOLERANCE_PCT}），"
        f"已用农学先验模型校正为 {prior_loss}%"
    )
    return payload, True, note


def _whitebox(context: dict, prior: dict, payload: dict, raw_response: str | None,
              source: str, corrected: bool, note: str | None, generated_at: str,
              model_name: str | None) -> list[dict]:
    """白盒三步：必须含真实读取到的数据值 + 真实命中/未命中的规则。"""
    plot = context["plot"]
    m = context["metrics"]
    hit_rules = [r for r in prior["rules"] if r["hit"]]
    miss_rules = [r for r in prior["rules"] if not r["hit"]]
    samples = context.get("window_samples") or []
    w = context.get("weather") or {}

    sources = context.get("metric_sources") or {}

    def src(metric: str, fallback: str) -> str:
        entry = sources.get(metric) or {}
        if not entry:
            return fallback
        note = entry.get("install_note") or ""
        return f"来自 {entry.get('device_code')}" + (f"（{note}）" if note else "")

    irrigation = prior.get("irrigation") or {}
    water_text = (
        f"水量平衡：亏缺 {irrigation.get('water_m3')} m³ ÷ 系统流量 "
        f"{irrigation.get('flow_m3_per_h')} m³/h → {irrigation.get('duration_min')} 分钟，"
        f"耗电 {irrigation.get('power_kwh')} kWh（{config.KWH_PER_M3} kWh/m³）；"
        if irrigation
        else ""
    )
    co2_text = f"棚内 CO₂ {_num(m.get('co2'), 'ppm')}、"

    step1 = (
        f"读取 {plot['name']} 最近 {context['window_minutes']} 分钟遥测，共 {len(samples)} 条样本"
        f"（设备 {', '.join(context.get('device_codes') or []) or '无'}）："
        f"气温 {_num(m.get('temperature'), '℃')}（{src('temperature', '本地块无环境站')}）、"
        f"湿度 {_num(m.get('humidity'), '%')}（{src('humidity', '本地块无环境站')}）、"
        f"墒情 {_num(m.get('soil_moisture'), '%')}（{src('soil_moisture', '本地块无墒情站')}）、"
        f"土温 {_num(m.get('soil_temp'), '℃')}（{src('soil_temp', '本地块无墒情站')}）、"
        + (co2_text if plot.get("scenario") == "greenhouse" else "")
        + f"电量 {_num(m.get('battery'), '%')}；"
        + water_text
        + (
            f"气象：{w.get('condition')} {w.get('temperature')}℃ 湿度 {w.get('humidity')}% "
            f"降水 {w.get('rainfall_mm')}mm {w.get('wind_dir')}风 {w.get('wind_level')} 级"
            if w
            else "气象：无数据"
        )
    )

    step2 = (
        "命中规则：" + ("；".join(f"{r['rule']} → {r['detail']}" for r in hit_rules) or "无")
        + "。未命中规则：" + ("；".join(r["rule"] for r in miss_rules) or "无")
        + f"。先验模型独立算出减产 {prior['yield_loss_pct']}%、耗电 {prior['power_kwh']} kWh。"
    )

    if source == "fallback":
        step3 = (
            "大模型不可用，已由本地农学先验规则引擎（knowledge.py）产出同结构结论："
            f"减产 {prior['yield_loss_pct']}%、耗电 {prior['power_kwh']} kWh，"
            "结构与数字口径与主模型路径完全一致。"
        )
    elif corrected:
        step3 = (
            f"{model_name} 原始返回：{payload.get('summary')}（原始减产 {raw_response and '见 raw_response'}）。"
            f"{note}。"
        )
    else:
        step3 = (
            f"{model_name} 返回减产 {payload['yield_loss_pct']}%、耗电 {payload['power_kwh']} kWh，"
            f"与先验模型 {prior['yield_loss_pct']}% 偏差 "
            f"{abs(float(payload['yield_loss_pct']) - float(prior['yield_loss_pct'])):.1f} 个百分点"
            f"（≤{config.REASONING_PRIOR_TOLERANCE_PCT}），采纳模型值。"
        )

    return [
        {"step": "环境数据读取", "detail": step1, "ts": generated_at},
        {"step": "匹配农学规则", "detail": step2, "ts": generated_at},
        {"step": "大模型结论生成", "detail": step3, "ts": generated_at},
    ]


# ---------------- 主入口 ----------------
def new_reasoning_id() -> str:
    stamp = now_iso().replace("-", "").replace(":", "").replace("+", "").replace("T", "T")[:15]
    return f"rs_{stamp}_{uuid.uuid4().hex[:4]}"


async def simulate(plot_code: str, node_id: str | None = None) -> dict:
    started = time.perf_counter()
    generated_at = now_iso()
    reasoning_id = new_reasoning_id()

    context = build_context(plot_code)
    if context is None:
        # V2.1 C-9：未知地块绝不编造结论，直接抛出由路由层转成 404。
        raise ValueError(f"plot not found: {plot_code}")
    prior = knowledge.evaluate(context)
    prompt = build_prompt(context, prior)

    payload: dict | None = None
    raw_response: str | None = None
    source = "fallback"
    model_name: str | None = None
    degraded = True
    error: str | None = None
    corrected = False
    note: str | None = None

    if not llm.is_configured():
        error = "大模型未配置（无 base_url 或 api_key），已降级为本地农学先验规则引擎"
    else:
        model_name = llm.default_model()
        result = await llm.complete_json(
            SYSTEM_PROMPT, render_user_prompt(context, prior), model_name,
            timeout_seconds=config.REASONING_TIMEOUT_SECONDS,
        )
        raw_response = result.answer
        if result.error or not result.answer:
            error = result.error or "大模型未返回内容"
        else:
            try:
                parsed = json.loads(result.answer)
                validated = schemas.ReasoningPayload.model_validate(parsed)
                payload = validated.model_dump()
                source = "primary"
                degraded = False
                model_name = result.model or model_name
                payload, corrected, note = cross_check(payload, prior)
            except (ValueError, ValidationError) as exc:
                error = f"大模型返回无法通过 Schema 校验：{type(exc).__name__}: {str(exc)[:300]}"
                log.warning("推演 Schema 校验失败：%s", error)

    if payload is None:
        built = knowledge.build_fallback_tree(context, prior, generated_at)
        tree = built["tree"]
        summary = built["summary"]
        yield_loss = built["yield_loss_pct"]
        power_kwh = built["power_kwh"]
    else:
        tree = payload["tree"]
        summary = payload["summary"]
        yield_loss = round(float(payload["yield_loss_pct"]), 1)
        power_kwh = round(float(payload["power_kwh"]), 2)

    whitebox = _whitebox(
        context, prior, {"yield_loss_pct": yield_loss, "power_kwh": power_kwh, "summary": summary},
        raw_response, source, corrected, note, generated_at, model_name,
    )

    latency_ms = int((time.perf_counter() - started) * 1000)
    response = {
        "reasoning_id": reasoning_id,
        "plot_code": plot_code,
        "generated_at": generated_at,
        "source": source,
        "model": model_name if source == "primary" else "local-agronomy-rules",
        "latency_ms": latency_ms,
        "degraded": degraded,
        "error": error,
        "corrected": corrected,
        "context": {
            "plot": context["plot"],
            "metrics": context["metrics"],
            "metrics_stats": context["metrics_stats"],
            "weather": context["weather"],
            "thresholds": context["thresholds"],
        },
        "tree": tree,
        "summary": summary,
        "yield_loss_pct": yield_loss,
        "power_kwh": power_kwh,
        "whitebox": whitebox,
        "prior": {
            "yield_loss_pct": prior["yield_loss_pct"],
            "power_kwh": prior["power_kwh"],
            "level": prior["level"],
            "hours_below_min": prior["hours_below_min"],
            "irrigation": prior.get("irrigation"),
        },
    }

    db.insert_reasoning({
        "id": reasoning_id,
        "plot_code": plot_code,
        "trigger": json.dumps({"source": "user_click", "node_id": node_id}, ensure_ascii=False),
        "prompt": prompt,
        "result": json.dumps(
            {**response, "raw_response": raw_response}, ensure_ascii=False
        ),
        "source": source,
        "model": response["model"],
        "latency_ms": latency_ms,
        "error": error,
        "created_at": generated_at,
    })
    return response


def detail(reasoning_id: str) -> dict | None:
    """GET /api/reasoning/{id}：含 prompt 原文与模型原始返回（白盒回看）。"""
    row = db.get_reasoning(reasoning_id)
    if row is None:
        return None
    try:
        result = json.loads(row["result"])
    except (ValueError, TypeError):
        result = {}
    result["reasoning_id"] = row["id"]
    result["plot_code"] = row["plot_code"]
    result["generated_at"] = row["created_at"]
    result["prompt"] = row["prompt"]
    return result


def history(limit: int) -> dict:
    limit = max(1, min(limit, config.REASONING_HISTORY_LIMIT))
    # 只取摘要字段 + result（用于回填 summary/yield_loss_pct），**不带 prompt**（减体积）。
    rows = db.query(
        """SELECT id, plot_code, source, model, latency_ms, error, created_at, result
           FROM reasoning ORDER BY created_at DESC, id DESC LIMIT ?""",
        (limit,),
    )
    items = []
    for row in rows:
        summary = None
        yield_loss = None
        try:
            stored = json.loads(row["result"])
            summary = stored.get("summary")
            yield_loss = stored.get("yield_loss_pct")
        except (ValueError, TypeError):
            pass
        items.append({
            "reasoning_id": row["id"],
            "plot_code": row["plot_code"],
            "source": row["source"],
            "model": row["model"],
            "latency_ms": row["latency_ms"],
            "degraded": row["source"] != "primary",
            "error": row["error"],
            "created_at": row["created_at"],
            "summary": summary,
            "yield_loss_pct": yield_loss,
        })
    return {"total": db.count_reasoning(), "items": items}
