"""OpenAI 兼容大模型封装 + 无 Key 自动降级的 Mock 农技专家。

两条铁律：
1. discover_models() 只读，失败不抛异常，回落到 mock 列表并把原因写进 error。
2. chat() 任何异常/超时都不得冒泡到路由 —— 一律降级为 Mock 答案，
   返回 degraded=True + error 说明，HTTP 仍为 200。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from . import config, runtime_config

MOCK_MODEL_ID = "mock-agronomist"
MOCK_MODEL_LABEL = "Mock 农技专家（离线演示）"

MOCK_MODELS = [
    {"id": MOCK_MODEL_ID, "label": MOCK_MODEL_LABEL, "source": "mock"},
    {"id": "mock-citrus-expert", "label": "Mock 柑橘栽培专家", "source": "mock"},
    {"id": "mock-irrigation", "label": "Mock 水肥一体化顾问", "source": "mock"},
]


def default_model() -> str:
    """运行时配置优先（runtime_config.json > 环境变量 > Mock，V2_PLAN.md 第 4 节）。"""
    return runtime_config.default_model()


def is_configured() -> bool:
    return runtime_config.is_configured()


def effective_base_url() -> str:
    """当前生效 base_url（可能来自 runtime_config.json 或环境变量）。"""
    return runtime_config.effective_base_url()


# ---------------- Mock 农技专家知识库 ----------------
# 按关键词匹配，覆盖柑橘黄化/墒情灌溉/温湿度/病虫害/施肥/花期保果等演示场景。
_MOCK_KB = [
    {
        "keywords": ["黄化", "黄叶", "叶子黄", "叶片发黄", "缺素", "黄龙"],
        "answer": (
            "柑橘叶片黄化先分清是“缺素型”还是“病理型”，两者的处理方向完全相反：\n"
            "1. 看叶脉：叶脉仍绿、脉间发黄 —— 典型缺镁/缺铁；整叶均匀褪绿并伴叶脉木栓化，"
            "则要警惕黄龙病。\n"
            "2. 看部位：老叶先黄多为缺氮/缺镁（可移动元素）；新叶先黄多为缺铁/缺锌。\n"
            "3. 查土壤：本园墒情长期低于 35% 时根系吸肥能力下降，会表现为“假性缺素”。"
            "建议先测土壤 pH（柑橘适宜 5.5~6.5），pH 偏高会固定铁、锌、锰。\n"
            "处理建议：\n"
            "- 缺镁：土施硫酸镁 0.5~1 kg/株，或叶面喷 0.2% 硫酸镁 + 0.3% 尿素，7~10 天一次，连喷 2~3 次。\n"
            "- 缺铁：叶面喷 0.1%~0.2% 螯合铁（EDDHA-Fe），配合增施有机肥改良土壤。\n"
            "- 若确诊黄龙病（斑驳状黄化 + 红鼻子果），无有效治疗药剂，必须及时挖除病株并统一防木虱，"
            "否则 2~3 年内整园蔓延。\n"
            "先做一步验证：随机取 10 株记录黄化叶位与新老叶分布，再决定按缺素还是按病害处理。"
        ),
    },
    {
        "keywords": ["墒情", "土壤水分", "浇水", "灌溉", "缺水", "干旱", "水分"],
        "answer": (
            "柑橘园墒情管理要点（以本园传感器数据为准）：\n"
            "1. 适宜区间：土壤墒情维持在 35%~80%，低于 35% 需灌溉，低于 25% 已属重度干旱，"
            "会直接引起落果和秋梢抽发不良。\n"
            "2. 灌溉阈值：墒情连续 2 小时低于 40% 即应启动滴灌，单次灌到 60%~70% 停止，"
            "避免大水漫灌造成根系缺氧。\n"
            "3. 时段选择：夏季选清晨 5:00~8:00 或傍晚 18:00 后灌溉，正午高温灌溉易伤根。\n"
            "4. 判断依据不只看墒情：结合 20 cm 土层手感——握之成团、落地散开即为适宜含水量。\n"
            "5. 覆盖保墒：树盘覆盖稻草或园艺地布，可减少蒸发 30% 以上，是性价比最高的保墒措施。\n"
            "提醒：墒情骤降后切忌一次猛灌，应分次小水勤灌，让根系逐步恢复吸收能力。"
        ),
    },
    {
        "keywords": ["温度", "高温", "低温", "霜冻", "寒潮", "日灼", "温湿度"],
        "answer": (
            "柑橘温湿度管理建议：\n"
            "1. 适宜范围：空气温度 15~35℃、相对湿度 40%~85%。超过 38℃ 或低于 5℃ 即进入"
            "胁迫区间，需要人工干预。\n"
            "2. 高温（>35℃）：提前灌水降低冠层温度，树冠喷施 1%~2% 石灰水或使用遮阳网；"
            "果实向阳面易发生日灼，需保留适量内膛枝遮阴。\n"
            "3. 低温（<5℃）：霜冻来临前 1~2 天灌透水（水的比热大，可缓冲降温）；"
            "幼树主干包扎稻草，或使用防霜布覆盖树冠。\n"
            "4. 湿度：持续高于 95% 时炭疽病、溃疡病风险显著上升，应及时疏除过密枝、"
            "改善通风透光，并在雨前喷施保护性杀菌剂（如代森锰锌）。\n"
            "5. 昼夜温差：秋季保持 8~10℃ 的昼夜温差有利于糖分积累和果实着色。"
        ),
    },
    {
        "keywords": ["病虫", "病害", "虫害", "红蜘蛛", "木虱", "潜叶蛾", "溃疡", "炭疽", "蚜虫", "防治"],
        "answer": (
            "柑橘主要病虫害防治（按当前季节高发排序）：\n"
            "1. 柑橘木虱：黄龙病唯一传播媒介，重点防秋梢和春梢期，新芽 1~2 cm 时用药，"
            "可选噻虫嗪、吡虫啉，注意轮换避免抗性。\n"
            "2. 红蜘蛛：高温干旱期爆发，叶片出现灰白失绿小点。用阿维菌素或螺螨酯，"
            "重点喷叶背，7 天后视虫口密度补喷一次。\n"
            "3. 潜叶蛾：夏秋梢抽发期危害最重，抹除零星早发梢、统一放梢，"
            "梢长 1~2 cm 时用药防治。\n"
            "4. 溃疡病：风雨传播，湿度高时流行。剪除病叶病枝带出园外销毁，"
            "雨前喷波尔多液或可杀得等铜制剂保护。\n"
            "5. 炭疽病：湿度 >95% 且树势弱时易发，需加强肥水管理增强树势，"
            "发病初期用咪鲜胺或苯醚甲环唑。\n"
            "原则：优先农业防治（清园、修剪、平衡施肥）+ 生物防治，化学防治按阈值用药，"
            "采收前严格遵守安全间隔期。"
        ),
    },
    {
        "keywords": ["施肥", "肥料", "氮", "磷", "钾", "有机肥", "水肥", "追肥"],
        "answer": (
            "柑橘施肥方案（以成龄结果树、亩产 3000 kg 为参照）：\n"
            "1. 全年施肥四次：芽前肥（2 月，促春梢）、稳果肥（5 月，减落果）、"
            "壮果促梢肥（7 月，占全年 40%）、采后肥（11 月，恢复树势）。\n"
            "2. 配方参考：每株年施纯氮 0.4~0.6 kg，氮磷钾比例约 1:0.5:0.8；"
            "壮果期偏重钾肥可提升糖度与果实硬度。\n"
            "3. 有机肥不可省：每亩年施腐熟有机肥 1000~1500 kg，可显著改善土壤团粒结构，"
            "提升根系对铁、锌等微量元素的吸收。\n"
            "4. 水肥一体化：配合滴灌少量多次，把单次施肥浓度控制在 0.2%~0.3%，"
            "避免烧根。\n"
            "5. 叶面追肥：新梢转绿期喷 0.3% 磷酸二氢钾 + 0.2% 尿素，"
            "阴雨天和正午高温时不要喷施。\n"
            "提醒：施肥前先看墒情，土壤过干时施肥易造成根系伤害，应先灌小水再施肥。"
        ),
    },
    {
        "keywords": ["花", "保果", "落果", "坐果", "畸形", "裂果"],
        "answer": (
            "柑橘保花保果与裂果防控：\n"
            "1. 保花：花前 10 天喷 0.2% 硼砂 + 0.3% 磷酸二氢钾，硼能显著提高花粉萌发率，"
            "花期避免使用杀虫剂伤害蜜蜂。\n"
            "2. 保果：谢花 2/3 时和第二次生理落果前各喷一次赤霉素（GA3）20~30 mg/L，"
            "配合芸苔素内酯效果更稳。\n"
            "3. 控梢保果：夏梢抽发会与幼果争夺养分，应及时抹除，"
            "或用多效唑控梢，保持梢果平衡。\n"
            "4. 裂果防控：裂果主因是土壤水分剧烈波动。保持墒情稳定在 45%~70%，"
            "久旱后切忌猛灌；果实膨大期叶面补钙（0.3% 硝酸钙）可增强果皮韧性。\n"
            "5. 疏果：按叶果比 60~80:1 留果，疏除病虫果、畸形果、小果，"
            "宁可少而优，不可多而劣。"
        ),
    },
]

_MOCK_FALLBACK = (
    "根据您描述的情况，我给出以下通用农技建议：\n"
    "1. 先定位问题类型：是水肥问题、病虫害问题，还是气象胁迫？"
    "建议结合本园实时数据判断 —— 空气温度适宜区间 15~35℃，相对湿度 40%~85%，"
    "土壤墒情 35%~80%。\n"
    "2. 看数据再动手：若墒情低于 35%，优先解决灌溉；若温度高于 38℃ 或低于 5℃，"
    "先做降温或防冻处理；若温湿度正常但长势异常，则转向营养与病虫害排查。\n"
    "3. 小范围试验：任何药剂或肥料方案先在 3~5 株上试用 7 天，确认无药害再全园推广。\n"
    "4. 记录留痕：把处理时间、用量、天气记录在案，便于下一季复盘。\n"
    "如需更精准的方案，请补充：作物品种、树龄、症状出现的部位（新叶/老叶/果实）、"
    "持续天数，以及最近一次施肥和用药情况。"
)


def mock_answer(question: str) -> str:
    text = question or ""
    for entry in _MOCK_KB:
        if any(kw in text for kw in entry["keywords"]):
            return entry["answer"]
    return _MOCK_FALLBACK


# ---------------- 远程调用 ----------------
@dataclass
class ChatResult:
    answer: str
    model: str
    degraded: bool
    latency_ms: int
    error: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    extra: dict = field(default_factory=dict)


def _headers() -> dict:
    # 每次都从运行时配置取（无进程内缓存），保证 WebUI 改配置后立刻生效。
    return {
        "Authorization": f"Bearer {runtime_config.effective_api_key()}",
        "Content-Type": "application/json",
    }


async def discover_models() -> tuple[list[dict], str | None, bool]:
    """返回 (items, error, degraded)。无 Key 或发现失败 → mock 列表 + 原因。"""
    base_url = runtime_config.effective_base_url()
    if not base_url:
        return list(MOCK_MODELS), "OPENAI_BASE_URL 未配置，已回落 Mock 模型列表", True
    if not runtime_config.effective_api_key():
        return list(MOCK_MODELS), "OPENAI_API_KEY 未配置，已回落 Mock 模型列表", True

    url = f"{base_url}/models"
    try:
        async with httpx.AsyncClient(timeout=config.OPENAI_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, headers=_headers())
            resp.raise_for_status()
            payload = resp.json()
        raw_items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(raw_items, list):
            return list(MOCK_MODELS), f"{url} 返回结构异常（缺少 data 列表），已回落 Mock 列表", True

        items = []
        for entry in raw_items:
            if isinstance(entry, dict) and entry.get("id"):
                items.append({"id": str(entry["id"]), "label": str(entry["id"]), "source": "remote"})
            elif isinstance(entry, str):
                items.append({"id": entry, "label": entry, "source": "remote"})
        if not items:
            return list(MOCK_MODELS), f"{url} 未返回任何模型，已回落 Mock 列表", True
        return items, None, False
    except Exception as exc:  # noqa: BLE001 —— 发现失败绝不能让接口 500
        return list(MOCK_MODELS), f"模型发现失败：{type(exc).__name__}: {exc}", True


async def chat(question: str, model: str | None) -> ChatResult:
    """真实调用；任何异常/超时 → Mock 答案 + degraded=True，绝不抛出。"""
    started = time.perf_counter()
    chosen = model or default_model()

    def elapsed() -> int:
        return int((time.perf_counter() - started) * 1000)

    base_url = runtime_config.effective_base_url()
    if not base_url or not runtime_config.effective_api_key():
        reason = "OPENAI_BASE_URL/OPENAI_API_KEY 未配置，已降级为 Mock 农技专家"
        return ChatResult(
            answer=mock_answer(question), model=MOCK_MODEL_ID, degraded=True,
            latency_ms=elapsed(), error=reason,
        )

    url = f"{base_url}/chat/completions"
    body = {
        "model": chosen,
        "messages": [
            {"role": "system", "content": "你是一位资深柑橘栽培农技专家，回答专业、可操作、给出量化指标。"},
            {"role": "user", "content": question},
        ],
        "temperature": 0.3,
    }

    last_error: str | None = None
    attempts = max(1, config.OPENAI_MAX_RETRIES + 1)
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=config.OPENAI_TIMEOUT_SECONDS) as client:
                resp = await client.post(url, headers=_headers(), json=body)
                resp.raise_for_status()
                payload = resp.json()
            choices = payload.get("choices") or []
            if not choices:
                raise ValueError("响应缺少 choices")
            answer = (choices[0].get("message") or {}).get("content")
            if not answer:
                raise ValueError("响应缺少 message.content")
            usage = payload.get("usage") or {}
            return ChatResult(
                answer=answer,
                model=payload.get("model") or chosen,
                degraded=False,
                latency_ms=elapsed(),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            )
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts - 1:
                continue

    reason = f"大模型调用失败（已重试 {attempts - 1} 次），已降级为 Mock 农技专家：{last_error}"
    return ChatResult(
        answer=mock_answer(question), model=MOCK_MODEL_ID, degraded=True,
        latency_ms=elapsed(), error=reason,
    )

# ---------------- 结构化 JSON 调用（V2 推演专用，V2_PLAN.md §8.3） ----------------
async def complete_json(system_prompt: str, user_prompt: str, model: str | None = None,
                        timeout_seconds: float | None = None) -> ChatResult:
    """推演用结构化调用：response_format={"type":"json_object"}、temperature=0.3。

    与 chat() 同样的铁律：任何超时/非 JSON/HTTP 错误都不冒泡，
    只把 error 写进 ChatResult，由调用方决定降级（reasoning.py 走 knowledge.py 规则引擎）。
    """
    started = time.perf_counter()

    def elapsed() -> int:
        return int((time.perf_counter() - started) * 1000)

    chosen = model or default_model()
    base_url = runtime_config.effective_base_url()
    api_key = runtime_config.effective_api_key()
    if not base_url or not api_key:
        return ChatResult(
            answer="", model=chosen, degraded=True, latency_ms=elapsed(),
            error="大模型未配置（无 base_url 或 api_key）",
        )

    url = f"{base_url}/chat/completions"
    body = {
        "model": chosen,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    timeout = float(timeout_seconds or config.REASONING_TIMEOUT_SECONDS)
    attempts = max(1, config.OPENAI_MAX_RETRIES + 1)
    last_error: str | None = None

    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=_headers(), json=body)
                resp.raise_for_status()
                payload = resp.json()
            choices = payload.get("choices") or []
            if not choices:
                raise ValueError("响应缺少 choices")
            content = (choices[0].get("message") or {}).get("content")
            if not content:
                raise ValueError("响应缺少 message.content")
            usage = payload.get("usage") or {}
            return ChatResult(
                answer=content,
                model=payload.get("model") or chosen,
                degraded=False,
                latency_ms=elapsed(),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            )
        except Exception as exc:  # noqa: BLE001 —— 绝不冒泡
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < attempts - 1:
                continue

    return ChatResult(
        answer="", model=chosen, degraded=True, latency_ms=elapsed(),
        error=f"大模型调用失败（已重试 {attempts - 1} 次）：{last_error}",
    )
