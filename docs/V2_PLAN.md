# V2.0 实施方案 —— 事件驱动的智慧农业数字孪生决策中枢

> 本文件是 V2.0 的施工图，与 `docs/CONTRACT.md`（V1 接口冻结真相）配合阅读。
> V2 对 V1 的 11 个 REST 接口**只增不改**，`/legacy` 路由保留 V1 大屏，确保现场可演示 V1→V2 演进。
> 状态：已按澄清访谈两轮共 8 项决策锁定；第 3 轮收口被用户取消，故未决项以「架构师决定」形式列在 §13 假设清单。

---

## 0. 定位与不变量

**定位**：从「大屏监控」升级为「可推演、可执行、可溯源」的决策中枢。卖点不是画得好看，而是
**同一份 Mock 传感数据，能长出带数字的因果推演树，并把推演结论变成真下发的 MQTT 指令**。

**不变量（V1 硬约束继续有效）**：
- 后端 Python FastAPI；数据库 SQLite（**绝不引入 MySQL**）；全部业务数据由代码模拟，不接真实硬件
- 单一后端容器同时托管前端静态产物；2C2G 机器可跑；禁止臃肿依赖
- `Dockerfile` + `docker-compose.yml` 一键启动；镜像由 GitHub Actions 构建推 ghcr.io，服务器只 pull

---

## 1. V1 → V2 变更总览

| 领域 | 处置 | 说明 |
|---|---|---|
| `/api/health` `/api/devices` `/api/telemetry/*` `/api/alerts*` `/api/ai/*` `/api/meta` | **保留** | 响应体逐字段不变，V1 前端可继续消费 |
| `backend/app/llm.py` | **改造** | 从「读环境变量」改为「读运行时配置」，新增结构化 JSON 输出能力 |
| `backend/app/mqtt_client.py` | **改造** | 新增订阅气象上行与指令回执；新增 publish 能力 |
| `backend/app/db.py` | **改造** | 新增 4 张表 DDL 与索引（幂等建表） |
| `simulator/mock_sensor.py` | **改造** | 新增气象发布 + 订阅下行指令并改变行为 |
| `frontend/src/App.vue` | **改名为 LegacyView** | V1 大屏原样保留，挂在 `/legacy` |
| 后端配置中心 / 推演 / 指令 / 气象 / 商城 | **新增** | 见 §2 |
| 前端 2.5D 地块 / 因果树 / 白盒 / 大字模式 / `/mobile` | **新增** | 见 §10 |

---

## 2. 新增文件与文件归属（严禁越界）

| 归属 | 文件 |
|---|---|
| **后端** | `backend/app/runtime_config.py`、`backend/app/knowledge.py`、`backend/app/reasoning.py`、`backend/app/command.py`、`backend/app/shop.py` |
| **后端** | `backend/app/routers/config.py`、`routers/reasoning.py`、`routers/command.py`、`routers/weather.py`、`routers/shop.py` |
| **后端（改造）** | `backend/app/{llm,db,config,schemas,mqtt_client,main}.py` |
| **模拟器** | `simulator/mock_sensor.py`（改造）、`simulator/weather.py`（新增） |
| **前端** | `frontend/src/views/{MainView,LegacyView,MobileView}.vue`、`frontend/src/router.js` |
| **前端** | `frontend/src/components/{PlotGrid25D,ReasoningTree,ReasoningWhitebox,SettingsModal,SkuCard,AccessiblePanel,MobileShell,CommandButton}.vue` |
| **前端（改造）** | `frontend/src/{main.js,api.js,config.js,App.vue}`、`styles/theme.css`、`components/AiChat.vue` |
| **部署与文档** | `docker-compose.yml`、`README.md`、`CHANGELOG.md`、`docs/API.md`、`docs/ARCHITECTURE.md`、`docs/V2_PITCH.md` |
| **调度方** | `docs/V2_PLAN.md`（本文件） |

---

## 3. 数据库变更（新增 4 表，启动时幂等建表）

```sql
CREATE TABLE IF NOT EXISTS reasoning (
  id          TEXT PRIMARY KEY,          -- rs_20261102T073000_ab12
  plot_code   TEXT NOT NULL,
  trigger     TEXT,                      -- JSON: {"source":"user_click","node_id":null}
  prompt      TEXT NOT NULL,             -- 完整 Prompt 原文（白盒回看）
  result      TEXT NOT NULL,             -- 完整推演树 JSON
  source      TEXT NOT NULL,             -- primary | fallback
  model       TEXT,
  latency_ms  INTEGER,
  error       TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reasoning_created ON reasoning(created_at DESC);

CREATE TABLE IF NOT EXISTS commands (
  id           TEXT PRIMARY KEY,         -- cmd_20261102T073005_cd34
  reasoning_id TEXT,                     -- 可空：允许不依赖推演的裸指令
  plot_code    TEXT NOT NULL,
  device_code  TEXT NOT NULL,
  node_id      TEXT,                     -- 推演树里被点击的那个绿色干预节点
  action       TEXT NOT NULL,            -- irrigation_on | irrigation_off | pesticide_dose | ventilation_on
  params       TEXT,                     -- JSON
  topic        TEXT NOT NULL,
  payload      TEXT NOT NULL,
  status       TEXT NOT NULL,            -- dispatched | executed | failed | timeout
  ack_at       TEXT,
  created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_commands_created ON commands(created_at DESC);

CREATE TABLE IF NOT EXISTS weather (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  plot_code    TEXT NOT NULL,
  ts           TEXT NOT NULL,
  temperature  REAL, humidity REAL, rainfall_mm REAL,
  wind_dir     TEXT, wind_level INTEGER, condition TEXT,
  UNIQUE(plot_code, ts)
);
CREATE INDEX IF NOT EXISTS idx_weather_plot_ts ON weather(plot_code, ts DESC);

CREATE TABLE IF NOT EXISTS skus (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  category    TEXT,
  price       REAL,
  unit        TEXT,
  image       TEXT,                      -- 图片占位标识（前端渲染占位块，不引外部图片）
  stock       INTEGER,
  description TEXT,
  keywords    TEXT                       -- 逗号分隔，用于按推演结论匹配挂载
);
```

启动时幂等 seed 6 条 SKU（抗旱保水剂 / 柑橘专用水溶肥 / 杀螨剂 / 叶面钙肥 / 滴灌带 / 土壤墒情探头），
**不覆盖用户改动**（`INSERT OR IGNORE`）。

---

## 4. 环境变量新增（21 → 25）

| 变量 | 默认 | 说明 |
|---|---|---|
| `RUNTIME_CONFIG_PATH` | `/data/runtime_config.json` | 配置中心持久化路径（容器内 /data 是具名卷） |
| `REASONING_TIMEOUT_SECONDS` | `45` | 推演比对话慢，独立超时（对话仍 20s） |
| `COMMAND_ACK_TIMEOUT_SECONDS` | `30` | 指令下发后等回执的时限，超时标 `timeout` |
| `WEATHER_INTERVAL_SECONDS` | `30` | 模拟器气象发布间隔 |

**运行时配置优先级**：`runtime_config.json` > 环境变量（`OPENAI_BASE_URL/API_KEY/MODEL`）> 内置 Mock。
即：**用户在 WebUI 齿轮里填的配置覆盖服务器环境变量，且不需要改代码、不需要重启容器**。

---

## 5. MQTT 主题（新增 1 上行 + 2 下行）

| 方向 | 主题 | QoS | 说明 |
|---|---|---|---|
| 上行（已有） | `agri/telemetry/{plot_code}/{device_code}` | 0 | 传感遥测，V1 不变 |
| **上行（新增）** | `agri/weather/{plot_code}` | 0 | 气象 Mock，每 30s 一条 |
| **下行（新增）** | `agri/command/{plot_code}/{device_code}` | **1** | 后端→模拟器的控制指令 |
| **上行（新增）** | `agri/command_ack/{plot_code}/{device_code}` | 1 | 模拟器回执，驱动 commands.status |

指令 payload：`{"command_id":"cmd_...","action":"irrigation_on","params":{"duration_min":40},"issued_at":"2026-11-02T07:30:05+08:00"}`
回执 payload：`{"command_id":"cmd_...","status":"executed","detail":"滴灌已开启，预计 40 分钟后停止","ts":"..."}`

---

## 6. 新增 REST 接口契约（12 条）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/config` | 当前生效配置；`api_key` **只回显掩码**（`sk-****abcd`），完整值永不返回 |
| PUT | `/api/config` | 写 `RUNTIME_CONFIG_PATH` 并**热生效**；`api_key` 传空串=保持不变，传 `null`=清除 |
| POST | `/api/config/test` | 用当前配置探活 `GET {base}/models`，返回 `{ok, latency_ms, models[], error}` |
| GET | `/api/models` | 运行时模型列表（V1 `/api/ai/models` 保留为别名） |
| POST | `/api/reasoning/simulate` | body `{plot_code, node_id?}` → 返回推演树 JSON（§7） |
| GET | `/api/reasoning/history?limit=20` | 推演历史列表（摘要字段） |
| GET | `/api/reasoning/{id}` | 单次推演详情，**含 prompt 原文与模型原始返回**（白盒） |
| POST | `/api/command/execute` | body `{reasoning_id?, plot_code, device_code, node_id?, action, params?}` → 发 MQTT + 落库 |
| GET | `/api/command/history?limit=20` | 指令历史与回执状态 |
| GET | `/api/weather/latest?plot_code=A` | 最新气象 + 未来 24h 模拟预报 |
| GET | `/api/shop/skus?keyword=抗旱` | Mock 农资 SKU 列表（按 `keywords` 模糊匹配） |
| GET | `/api/meta` | **扩展**（超集，V1 字段逐字保留）：`plots[]` 增加 `name`、`crop`、`area_mu`、`stage` 与 2.5D 网格坐标 `{col,row}`（`devices[]` 是 V1 既有字段，非新增）；顶层新增 `crops`、`weather` 段 |

所有新接口沿用 V1 的错误约定：字段校验失败 422、资源不存在 404 `{"detail":"..."}`、LLM 不可用**不报 5xx**而是降级返回。

---

## 7. 核心数据结构：推演树 JSON（冻结，前端按此渲染）

```json
{
  "reasoning_id": "rs_20261102T073000_ab12",
  "plot_code": "A",
  "generated_at": "2026-11-02T07:30:00+08:00",
  "source": "primary",
  "model": "qwen-plus",
  "latency_ms": 1834,
  "degraded": false,
  "error": null,
  "context": {
    "plot": {"plot_code":"A","name":"A区柑橘园","crop":"柑橘(沃柑)","area_mu":12.5,"stage":"果实膨大期"},
    "metrics": {"temperature":35.2,"humidity":28.0,"soil_moisture":15.0,"soil_temp":26.1,"battery":92},
    "weather": {"temperature":36.0,"humidity":25.0,"rainfall_mm":0.0,"wind_dir":"东南","wind_level":2,"condition":"晴"},
    "thresholds": {"temperature":{"min":15.0,"max":35.0,"critical_min":5.0,"critical_max":38.0}}
  },
  "tree": {
    "nodes": [
      {"id":"root","type":"current","level":0,"label":"当前数据","sub":"墒情 15% · 气温 35.2℃","severity":"warn"},
      {"id":"risk_1","type":"risk","level":1,"parent":"root","label":"减产风险 20%","sub":"持续缺水胁迫 >24h","severity":"high"},
      {"id":"plan_1","type":"plan","level":1,"parent":"root","label":"开启滴灌 40 分钟","sub":"预计耗电 1.9 度 · 墒情回升 18%","severity":"good",
       "command":{"action":"irrigation_on","params":{"duration_min":40},"device_code":"FJ-CITRUS-A02"},
       "effect":{"soil_moisture_delta":18.0,"yield_recover_pct":14.0},
       "sku_keywords":["滴灌带","抗旱保水剂"]}
    ],
    "links": [{"source":"root","target":"risk_1"},{"source":"root","target":"plan_1"}]
  },
  "summary": "A区柑橘园处于中度水分胁迫，建议 6 小时内启动滴灌。",
  "yield_loss_pct": 20,
  "power_kwh": 1.9,
  "whitebox": [
    {"step":"环境数据读取","detail":"读取 A 区 4 台设备最近 10 分钟遥测 + 气象 Mock","ts":"..."},
    {"step":"匹配农学规则","detail":"命中『土壤墒情 <25% 持续 24h → 减产 15~25%』；后端先验模型独立算出 18.4%","ts":"..."},
    {"step":"大模型结论生成","detail":"qwen-plus 返回 20%，与先验模型偏差 1.6 个百分点（<15），采纳模型值","ts":"..."}
  ]
}
```

**前端零硬编码红线**：`yield_loss_pct`、`power_kwh`、`effect.*` 一律取自接口。
前端不得出现任何形如 `20`、`1.8` 的推演数字常量。

---

## 8. Context Engineering：Prompt 封装逻辑（后端 `reasoning.py`）

### 8.1 组装流水线

```
plot_code
  → 地块元数据（config.PLOTS：名称/作物/面积/物候期）
  → 最近 10 分钟遥测（db：均值 + 最新值 + 极值）
  → 最新气象 + 未来 24h 模拟预报（weather 表）
  → 阈值快照（config.THRESHOLDS，与 /api/meta 同源）
  → 农学先验模型独立计算（knowledge.py，不依赖大模型）
  → 渲染成中文上下文块 → 拼 System + Schema → 调 LLM → pydantic 校验 → 回填先验交叉校验结果
```

### 8.2 System Prompt（固定）

```
你是资深柑橘栽培与农业物联网决策专家。你会收到某地块的实时传感、气象与阈值数据。
你的任务是基于这些数据做胁迫诊断与干预推演。
硬性要求：
1. 只输出一个 JSON 对象，不要 Markdown 代码块、不要任何解释文字；
2. 减产率与耗电量必须是数字，且必须由你基于上下文推理得出，不得照抄输入；
3. 干预策略 2~3 条，每条必须可执行、有量化收益；
4. 严格遵循给定 JSON Schema。
```

### 8.3 User Prompt 模板（Context Engineering 的实体）

```
【地块】{plot.name}｜作物 {plot.crop}｜面积 {plot.area_mu} 亩｜物候期 {plot.stage}
【实时传感（最近 10 分钟）】
空气温度 {m.temperature}℃（正常 {t.min}~{t.max}，critical >{t.critical_max}）
空气湿度 {m.humidity}%（正常 {h.min}~{h.max}，critical >{h.critical_max} 或 <{h.critical_min}）
土壤墒情 {m.soil_moisture}%（正常 {s.min}~{s.max}，critical <{s.critical_min}）
土壤温度 {m.soil_temp}℃｜设备电量 {m.battery}%
【气象（未来 24h 模拟预报）】
气温 {w.temperature}℃｜湿度 {w.humidity}%｜降水 {w.rainfall_mm}mm｜{w.wind_dir}风 {w.wind_level} 级｜{w.condition}
【后端农学先验模型参考（独立算出，仅供交叉校验，你可以不同意并给出你的判断）】
水分胁迫减产估计 {prior.yield_loss_pct}%｜滴灌一次预计耗电 {prior.power_kwh} kWh（按 {area_mu} 亩 × 0.15 kWh/亩）
【任务】判断胁迫等级；给出减产风险百分比（整数 0~100）；给出 2~3 条干预策略及预计耗电与墒情回升；
如涉及植保用药给出药品关键词；输出 3 步白盒推演过程。
【输出 JSON Schema】{inline_schema}
```

调用参数：`temperature=0.3`、`response_format={"type":"json_object"}`、`timeout=REASONING_TIMEOUT_SECONDS`、
`max_retries=1`，走 `POST {base}/chat/completions`（OpenAI 兼容协议，与 V1 `llm.py` 同一套封装）。

### 8.4 降级与交叉校验（三段式，答辩核心）

| 情况 | 行为 | 前端标签 |
|---|---|---|
| LLM 返回合法 JSON | 采纳，`source=primary` | 【主模型生成】 |
| LLM 数字与先验模型偏差 >15 个百分点 | **以后端先验模型为准**，白盒写明「已用农学先验模型校正」 | 【主模型生成·已校正】 |
| 无 Key / 超时 / 非 JSON / Schema 校验失败 | `knowledge.py` 规则引擎产出同结构 JSON，`source=fallback` | 【离线降级策略】 |

无论哪条路，**返回结构与数字口径完全一致**，前端渲染逻辑不分叉。

---

## 9. 指令闭环时序（真闭环，非 Toast 假动作）

```
前端点击绿色节点旁的【一键执行指令】
  → POST /api/command/execute
  → 后端 INSERT commands(status=dispatched) + publish agri/command/{plot}/{device} (QoS 1)
  → 前端立即 Toast：「指令已通过 MQTT 模拟下发」（带 command_id）
  → 模拟器收到 → 改变该地块行为（irrigation_on：墒情基线抬升并随时间回升；pesticide_dose：记一次施药）
  → 模拟器 publish agri/command_ack/{plot}/{device}
  → 后端更新 status=executed, ack_at
  → 前端轮询 /api/command/history 看到 status 变化，节点旁状态点由黄转绿
  → 30s 无回执 → status=timeout（前端标红，证明链路可观测）
```

---

## 10. 前端架构

**路由（手写极简路由，**不引入 vue-router**）**：`/` = V2 主界面、`/legacy` = V1 大屏、`/mobile` = 移动端预览。
实现：`frontend/src/router.js` 用 `history.pushState` + `popstate` 维护一个 `reactive({path})`，`App.vue` 按 path 切视图。
理由：只有 3 个路由，引入 vue-router 增加 ~20KB 与一个依赖，违背「禁止臃肿依赖」硬约束。

**主界面三栏**：左 = 2.5D 地块网格（`PlotGrid25D`，CSS `perspective` + `rotateX(55deg)`，点击地块触发推演）；
中 = 因果推演树（`ReasoningTree`，ECharts Graph，节点发光、动态生长动画，绿色干预节点挂 `CommandButton` 与 `SkuCard`）；
下 = AI 双轨对话（`AiChat` 改造：气泡带【主模型生成】/【离线降级策略】标签 + 【展开推演逻辑】折叠面板 `ReasoningWhitebox`）。
右上角 = 齿轮 `SettingsModal`（base_url / api_key / model，保存即热生效，带「测试连接」）+ 大字模式 Switch。

**主题**（`styles/theme.css` 全量替换）：底 `#121212`、荧光青 `#00E5FF`、辅助绿 `#00E676`、告警红 `#FF3B30`、
正文 `#E0E0E0`、次要 `#8A8A8A`、面板 `rgba(255,255,255,0.04)` + `1px solid rgba(0,229,255,0.18)`、极细描边、无渐变堆砌。

**大字模式**（`AccessiblePanel`）：开启后隐藏推演树/图表/对话，全屏重排为超大字号，只保留最高优先级告警与干预建议
（如绿底白字大卡：【A区缺水，请开泵】），一键关闭可逆。

**移动端**（`/mobile`）：`MobileShell` 手机外壳 + 拍照识病大按钮（占位图 + 调用 `/api/ai/chat` 带识病意图）、
地块数据卡片（`/api/devices` + `/api/telemetry/latest`）、待办任务（`/api/alerts?only_unacked=true`）。

---

## 11. 三步交付划分与验收标准

### 第一步：后端全量（本次派发）
产出：§2 全部后端与模拟器文件 + §3 建表 + §4 变量 + §5 主题 + §6 接口 + §7/§8 推演与 Prompt + §9 闭环的服务端。
**验收标准（缺一不可）**：
1. 无 Key 时 `POST /api/reasoning/simulate` 返回 **HTTP 200** 且 `source="fallback"`、树里有数字、`whitebox` 三步齐全；
2. 本地起**假 OpenAI 兼容服务**（`/v1/models` + `/v1/chat/completions` 返回合法推演 JSON）后，
   同一接口返回 `source="primary"`、`model` 为假服务声明的模型名，且 `GET /api/reasoning/{id}` 能取回 **prompt 原文**；
3. 假服务返回**非 JSON** 或 **HTTP 500** 时，接口仍 200 且自动降级（`degraded=true`），**不冒泡异常**；
4. `PUT /api/config` 写文件后**立即生效**（无需重启），`GET /api/config` 的 `api_key` 是掩码，
   且 `grep` 证明完整 Key 不出现在任何响应体、日志与仓库文件中；
5. `POST /api/command/execute` → 模拟器收到 → 回执 → `status` 由 `dispatched` 变 `executed`（端到端真跑通）；
6. 模拟器收到 `irrigation_on` 后，该地块 `soil_moisture` 曲线**确实回升**（提供前后数值）；
7. 30s 无回执时 `status=timeout`；
8. V1 的 11 个接口回归全绿（响应体逐字段不变）；
9. 4 张新表 + 索引在 SQLite 中实际存在，`PRAGMA journal_mode` 仍为 `wal`。

### 第二步：前端核心
2.5D 地块 + 因果树 + 白盒面板 + 齿轮配置 + 双轨标签 + SKU 卡片 + 指令按钮 + 暗夜灰主题。
验收：`npm run build` 成功且产物体积记录；headless Chrome 实机点击地块 → 树生长出带数字的红/绿分支 →
点绿色节点旁按钮 → Toast 出现且节点状态点变绿；齿轮改配置 → 保存 → 界面模型名变化。

### 第三步：大字模式 + /mobile + 答辩话术 + 文档
验收：`/legacy` `/mobile` 深链直接访问 200 且不白屏；大字模式开关可逆且隐藏复杂面板；
`docs/V2_PITCH.md` 含「减产 20% 怎么算的」完整话术；README/CHANGELOG/API.md/ARCHITECTURE.md 同步。

### 收尾：服务器覆盖部署
覆盖现有三容器，从**外网**直连复测全部新接口 + 推演 + 指令闭环 + `/legacy` + `/mobile`。

---

## 12. 风险与对策

| 风险 | 对策 |
|---|---|
| LLM 返回非 JSON / 缺字段 | pydantic 严格校验 + 三段式降级（§8.4），接口永不 5xx |
| 推演耗时拖垮大屏 | 独立 45s 超时 + 前端骨架屏 + 历史侧栏可回看，不阻塞轮询 |
| 2C2G 内存 | 仍是单后端容器；推演不落大对象（prompt 截断到 8KB）；不新增常驻进程 |
| 前端依赖膨胀 | 不引 vue-router / UI 框架 / 状态库，全部手写 |
| 指令闭环在服务器上不可见 | 回执落库 + `/api/command/history` 外网可查，答辩时直接展示状态流转 |
| 私人镜像代理地址泄漏 | README/CHANGELOG 中的私有加速地址已全部替换为占位符（`<你的镜像加速地址>` / `<你的代理域名>`），`grep` 复核零残留 |

---

## 13. 架构师决定项（第 3 轮收口被取消，按此执行）

1. **不引入 vue-router**，手写 3 路由（省依赖，符合硬约束）
2. `/legacy` 用**同一 bundle 内路由分支**保留 V1 界面，不产出第二份静态产物
3. 新增 `weather` 表与 `agri/weather/{plot}` 主题（任务书要求「气象」Mock，V1 无此数据源）
4. 推演独立超时 `REASONING_TIMEOUT_SECONDS=45`（对话仍 20s）
5. 农学先验模型口径：亩均滴灌耗电 `0.15 kWh/亩`；水分胁迫减产按缺水深度与持续时间插值（15~25%）
6. SKU 落 DB 表并启动幂等 seed 6 条
7. README 中 daemon.json 段改为 `<你的镜像加速地址>` 占位符，不写死任何具体地址
8. 指令回执走 MQTT ack 主题，30s 未回执标 `timeout`

**回退触发器**：若用户对以上任一条提出异议，只需改动对应小节，其余不受影响。
