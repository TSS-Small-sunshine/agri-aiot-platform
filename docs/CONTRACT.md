# 接口契约（冻结版 v1，V2.0 增量见 §9，V2.1 第一步见 §10，V2.1 第二步见 §11）—— 三路开发必须严格遵守

> 本文件是并行开发的唯一接口真相。任何一方不得单方面修改；如需变更，先改本文件。

## 0. 仓库
- 本地路径：`D:\Agent工作区\职规\agri-aiot-platform`
- 远程：GitHub 公开仓库（由调度方建仓并推送）
- 技术栈锁定：Python FastAPI + SQLite(WAL) 后端；Vue3 + Vite 前端；MQTT(eclipse-mosquitto)；Docker Compose 一键启动

## 1. 文件归属（严禁越界）
| 归属 | 路径 |
|---|---|
| 后端负责人 | `backend/**`（含 backend/Dockerfile）、`simulator/**`、`mosquitto/**`、`scripts/seed_history.py` |
| 前端负责人 | `frontend/**`（不含 Dockerfile，前端由 backend/Dockerfile 多阶段构建） |
| 部署负责人 | `.github/**`、`docker-compose.yml`、`README.md`、`CHANGELOG.md`、`scripts/dev_up.sh`、`scripts/dev_up.ps1`、`.env.example`、`.gitignore`、`docs/API.md` |
| 调度方 | `docs/PLAN.md`、`docs/ARCHITECTURE.md`、`docs/CONTRACT.md` |

## 2. 环境变量（.env.example 全量，代码只从环境变量读，禁止硬编码）
```
APP_PORT=8000
APP_VERSION=2.0.0
DB_PATH=/data/agri.db
DATA_DIR=/data
MQTT_HOST=mosquitto
MQTT_PORT=1883
MQTT_TOPIC=agri/telemetry/+/+
DEVICE_OFFLINE_SECONDS=30
TELEMETRY_RETENTION_DAYS=7
HISTORY_HOURS_MAX=168
CORS_ORIGINS=*
OPENAI_BASE_URL=
OPENAI_API_KEY=
OPENAI_MODEL=
OPENAI_TIMEOUT_SECONDS=20
OPENAI_MAX_RETRIES=1
AI_HISTORY_LIMIT=50
SIM_INTERVAL_SECONDS=5
SIM_DEVICES=FJ-CITRUS-A01,FJ-CITRUS-A02,FJ-CITRUS-B01,FJ-CITRUS-B02,FJ-MUSH-C01
SIM_IRRIGATION_RATE_PCT_PER_S=0.008
SIM_DEMO_ACCELERATION=30
SIM_SCENARIO=normal
SIM_BAD_PROBABILITY=0
SIM_PACKET_LOSS=0
ALERT_COOLDOWN_SECONDS=300
RUNTIME_CONFIG_PATH=/data/runtime_config.json
REASONING_TIMEOUT_SECONDS=45
COMMAND_ACK_TIMEOUT_SECONDS=30
WEATHER_INTERVAL_SECONDS=30
```

> 契约修订 v1.1：新增 `SIM_BAD_PROBABILITY`（模拟器越界注入概率，设 0 可关闭）与 `ALERT_COOLDOWN_SECONDS`（同 device_code+metric+level 的告警冷却秒数，防 5s 高频刷表）。
>
> 契约修订 v1.2（V2.0）：
> - `RUNTIME_CONFIG_PATH`：WebUI 配置中心落盘路径，默认 `{DATA_DIR}/runtime_config.json`。该文件保存用户在大屏齿轮弹窗里填写的 base_url / api_key / model，**优先级高于环境变量**，且不得入库（.gitignore 必须显式覆盖）。
> - `REASONING_TIMEOUT_SECONDS`：单次推演调用大模型的超时秒数，默认 45（比 `OPENAI_TIMEOUT_SECONDS` 宽，推演 prompt 更长）。
> - `COMMAND_ACK_TIMEOUT_SECONDS`：指令下发后等待模拟器回执的秒数，超时把命令标记为 `timeout`，默认 30。
> - `WEATHER_INTERVAL_SECONDS`：模拟器上报气象数据的间隔秒数，默认 30（与 5s 遥测解耦）。
>
> 配置优先级（三者取第一个有值的）：`runtime_config.json` > 环境变量 > 内置 Mock。无任何 Key 时 AI 与推演均降级为本地规则库，HTTP 仍 200。
>
> 契约修订 v1.3（V2.1 第一步，当时 28 个变量）：
> - `SIM_IRRIGATION_RATE_PCT_PER_S`：滴灌**真实**速率（%/秒），默认 0.008（≈28.8 点/小时）。后端 `knowledge.py` 与模拟器共用该常量。
> - `SIM_DEMO_ACCELERATION`：演示加速倍率，默认 30（设 1 = 完全真实时间）。生效速率 = 上者 × 本值。
> - `SIM_SCENARIO`：连续演示场景，`normal`(默认) | `drought` | `heat` | `disease` | `cold`。
> - `SIM_BAD_PROBABILITY` 默认由 0.12 改为 **0**（默认不注入单点脏值）；`APP_VERSION` 由 1.0.0 改为 2.0.0。
> - 湿度阈值与两条抑制规则变更见 §6，完整裁定见 §10。

## 3. MQTT 约定
- 主题：`agri/telemetry/{plot_code}/{device_code}`（如 `agri/telemetry/A/FJ-CITRUS-A01`）
- QoS 0，非保留消息，payload 为 JSON：
```json
{"device_code":"FJ-CITRUS-A01","plot_code":"A","type":"env",
 "ts":"2026-01-01T12:00:00+08:00","temperature":26.4,"humidity":68.2,
 "soil_moisture":52.1,"soil_temp":22.7,"battery":93.5}
```
- 设备清单（模拟器与后端种子数据必须一致）：
  | device_code | name | plot_code | plot_name | type |
  |---|---|---|---|---|
  | FJ-CITRUS-A01 | A区柑橘园环境站 | A | A区·柑橘示范园 | env |
  | FJ-CITRUS-A02 | A区柑橘园墒情站 | A | A区·柑橘示范园 | soil |
  | FJ-CITRUS-B01 | B区柑橘园环境站 | B | B区·柑橘试验园 | env |
  | FJ-CITRUS-B02 | B区柑橘园墒情站 | B | B区·柑橘试验园 | soil |
| FJ-MUSH-C01 | C区温室环境站 | C | C区·闽宁协作温室菇棚 | env（+CO₂） |

## 4. 数据库 DDL（SQLite，启动时幂等建表；PRAGMA journal_mode=WAL）
```sql
CREATE TABLE IF NOT EXISTS devices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_code TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  plot_code TEXT NOT NULL, plot_name TEXT, type TEXT NOT NULL,
  location TEXT, status TEXT DEFAULT 'online', last_seen TEXT,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS telemetry (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_code TEXT NOT NULL, ts TEXT NOT NULL,
  temperature REAL, humidity REAL, soil_moisture REAL, soil_temp REAL,
  battery REAL, raw TEXT);
CREATE INDEX IF NOT EXISTS idx_telemetry_device_ts ON telemetry(device_code, ts);
CREATE INDEX IF NOT EXISTS idx_telemetry_ts ON telemetry(ts);
CREATE TABLE IF NOT EXISTS ai_chat (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT, question TEXT NOT NULL, answer TEXT,
  model TEXT, degraded INTEGER DEFAULT 0, latency_ms INTEGER,
  prompt_tokens INTEGER, completion_tokens INTEGER, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_ai_chat_created ON ai_chat(created_at DESC);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_code TEXT NOT NULL, metric TEXT NOT NULL, value REAL, threshold REAL,
  level TEXT, message TEXT, acked INTEGER DEFAULT 0, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at DESC);
```
所有时间字段一律 ISO8601 带时区字符串（如 `2026-01-01T12:00:00+08:00`）。

## 5. REST 接口（响应体逐字段冻结，前端按此消费）
统一前缀 `/api`。错误一律 FastAPI 标准 `{"detail": "..."}`。

**GET /api/health**
```json
{"status":"ok","version":"1.0.0","uptime_s":12.3,
 "db":{"ok":true,"path":"/data/agri.db"},
 "mqtt":{"connected":true,"host":"mosquitto","port":1883,"topic":"agri/telemetry/+/+"},
 "llm":{"configured":false,"base_url":null,"degraded":true}}
```

**GET /api/devices** → `{"total":4,"online":3,"offline":1,"items":[...]}`
item：
```json
{"device_code":"FJ-CITRUS-A01","name":"A区柑橘园环境站","plot_code":"A","plot_name":"A区·柑橘示范园",
 "type":"env","location":"福建省南平市·A区","status":"online","last_seen":"2026-01-01T12:00:00+08:00",
 "latest":{"ts":"...","temperature":26.4,"humidity":68.2,"soil_moisture":52.1,"soil_temp":22.7,"battery":93.5}}
```
`status` 取值 `online`|`offline`（last_seen 距今 > DEVICE_OFFLINE_SECONDS 即 offline）。

**GET /api/telemetry/latest** → `{"items":[ <同 devices 的 latest 对象，额外含 device_code, plot_code> ]}`

**GET /api/telemetry/history** query: `device_code`(必填), `hours`(默认 1，上限 HISTORY_HOURS_MAX), `limit`(默认 720，上限 5000), `metric`(可选，逗号分隔的列名白名单；V2.1 §11.2)
→ `{"device_code":"...","hours":1,"count":120,"points":[{"ts":"...","temperature":26.4,"humidity":68.2,"soil_moisture":52.1,"soil_temp":22.7}]}`
points 按 ts 升序。`metric` 只允许收窄到 `_HISTORY_METRICS` 白名单内的列（ts 恒在），未命中白名单的列一律不返回；非温室设备的 `co2` 恒为 null（V2.1 §11.1）。

**GET /api/telemetry/summary** query: `hours`(默认 24)
→ `{"hours":24,"samples":1440,
 "temperature":{"avg":25.1,"min":18.2,"max":33.9},
 "humidity":{"avg":66.0,"min":41.0,"max":88.0},
 "soil_moisture":{"avg":51.2,"min":28.4,"max":72.1}}`
无数据时各字段为 null。

**GET /api/alerts** query: `limit`(默认 50), `only_unacked`(默认 false)
→ `{"total":12,"unacked":3,"items":[{"id":1,"device_code":"FJ-CITRUS-A02","metric":"soil_moisture","value":28.4,"threshold":35.0,"level":"warning","message":"A区柑橘园墒情站 土壤墒情 28.4% 低于下限 35%","acked":0,"created_at":"..."}]}`
items 按 created_at 降序。

**POST /api/alerts/{id}/ack** → `{"ok":true,"id":1}`；不存在 → 404 `{"detail":"alert not found"}`

**GET /api/ai/models** → `{"configured":false,"degraded":true,"default_model":"mock-agronomist",
 "error":null,"items":[{"id":"mock-agronomist","label":"Mock 农技专家（离线演示）","source":"mock"}]}`
有 Key 时 source=`remote`，items 来自 `GET {OPENAI_BASE_URL}/models`；发现失败则回落到 mock 列表并把原因写进 `error`。

**POST /api/ai/chat** body: `{"question":"柑橘叶子黄了怎么办","session_id":"s1","model":"qwen-plus"}`（model 可省略 → 用 default_model）
→ `{"answer":"...","model":"mock-agronomist","degraded":true,"latency_ms":12,"session_id":"s1","created_at":"...","error":null}`
要求：真实调用超时（OPENAI_TIMEOUT_SECONDS）或任何异常 → 返回 Mock 答案且 `degraded=true`、`error` 写明原因，HTTP 仍为 200。question 为空 → 422。

**GET /api/ai/history** query: `limit`(默认 20，上限 AI_HISTORY_LIMIT)
→ `{"total":37,"items":[{"id":7,"question":"...","answer":"...","model":"...","degraded":0,"latency_ms":1200,"created_at":"..."}]}` 降序。

**GET /api/meta** → `{"plots":[{"plot_code":"A","plot_name":"A区·柑橘示范园","devices":["FJ-CITRUS-A01","FJ-CITRUS-A02"]}],"thresholds":{"temperature":{"min":5,"max":35,"critical_min":0,"critical_max":38},"humidity":{"min":40,"max":92,"critical_min":30,"critical_max":97},"soil_moisture":{"min":35,"max":80,"critical_min":25},"co2":{"min":400,"max":1200,"critical_min":300,"critical_max":1500}},"sim_interval_seconds":5}
> V2.1 §11：该接口按**超集**验收（§9.4 已裁定）。`thresholds.soil_moisture` 是**按地块土壤质地分档后实际生效**的值（A 壤土 35 / B 砂壤 28 / C 无墒情段）；`co2` 段只在有温室设备的地块出现；`plots[]` 另增 `name/crop/area_mu/stage/col/row/scenario/soil_texture/metrics/thresholds`。`

## 6. 告警阈值（config.py 常量，同时经 /api/meta 暴露给前端）
- temperature：正常 **5~35℃**；>38 或 <5 → critical；35~38 → warning（V2.1 §11.5：下限由 15℃ 下修到 5℃）
- humidity：正常 40~92%；<40 或 >92 → warning；<30 或 >97 → critical（消除原 30~40 / 85~95 的静默带）
  - **V2.1 抑制规则 C-4**：湿度告警必须同时满足 ① 同一设备最近 `ALERT_SUSTAINED_SAMPLES`(3) 个采样全部越界，② 该设备最近一次气温 ≥ `HUMIDITY_ALERT_MIN_TEMPERATURE`(20℃)。福建夜间露点高，单点高湿是常态，不抑制会天天刷屏。
  - **V2.1 §11.3 长时高湿改判病害风险**：连续高湿 ≥ `HUMIDITY_RISK_MIN_HOURS`(6.0) 小时**且**气温落在 `20~28℃` 时，不再刷单点湿度告警，改出「炭疽病风险提示」（回溯窗口 `HUMIDITY_RISK_WINDOW_HOURS`=24h 有界查询）。单点/短时高湿按 C-4 抑制。
  - 连续计数规则对 temperature / soil_moisture 同样生效（同一设备、同一指标）。
- soil_moisture：正常 35~80%；<35 → warning；<25 → critical
  - **V2.1 §11.4 按土壤质地分档**（`SOIL_TEXTURE_THRESHOLDS`）：砂壤 `28/80/20`、壤土 `35/80/25`、黏壤 `40/80/30`；地块未标注质地时取 `DEFAULT_SOIL_TEXTURE`（壤土）。`/api/meta` 暴露的是该地块**生效后**的值。
- co2（仅温室）：正常 400~1200 ppm；>1200 或 <400 → warning；>1500 或 <300 → critical（V2.1 §11.1）

## 7. 前端约束
- 静态构建产物输出到 `frontend/dist`（`vite.config.js` 的 `build.outDir`，**不要**直接写进 backend/，避免并行开发互相踩）
- 后端用 StaticFiles 挂载 `STATIC_DIR`（默认 `backend/app/static`），SPA 路由回退到 index.html；`STATIC_DIR` 不存在时 `/` 返回一行 JSON 提示（不得报 500）
- 容器内：backend/Dockerfile 多阶段构建前端后把 `frontend/dist` 拷到 `/app/app/static`
- 本地裸机验证：由 dev_up 脚本把 `frontend/dist` 拷到 `backend/app/static`
- 开发期 vite devServer 代理 `/api` → `http://127.0.0.1:8000`
- 主题：深色科技感（背景 #0a1020 系、青色/绿色高亮、发光边框）
- 必须实现组件：RealtimeChart(温湿度折线，5s 刷新)、DeviceStatusCard(绿/红点)、SoilGauge(墒情仪表)、AlertPanel(红色告警)、PlotMap(多地块点位图)、AiChat(对话 + 模型下拉 + 历史侧栏)
- 轮询间隔统一 5000ms；请求失败必须在 UI 上可见（不静默吞错）
- 依赖仅限：vue、echarts、vite、@vitejs/plugin-vue（不得引入 UI 框架/状态库）

## 8. 端口与运行
- 后端容器暴露 8000，宿主机映射 `8000:8000`
- mosquitto 容器 1883（仅内网，不映射到宿主机）
- 前端由后端同端口托管，无独立容器
- compose 服务名固定：`backend`、`mosquitto`、`simulator`；数据卷 `agri-data` 挂载到 `/data`

## 9. V2.0 契约修订记录（调度方裁定）

> V2.0 施工图见 `docs/V2_PLAN.md`。本节记录第一步后端交付后由调度方裁定的 5 个契约缺口。

### 9.1 湿度阈值静默带（已修，v1.1 起生效）
原 `humidity` 只有 30~40 / 85~95 两段无定义 → 改为对称双档（v1.1：正常 40~85；v1.3 进一步放宽为 **40~92**，见 §6 与 §10.4）。已落到 `backend/app/config.py` 的 `THRESHOLDS` 与 `/api/meta`。

### 9.2 新增环境变量（v1.2）
`RUNTIME_CONFIG_PATH` / `REASONING_TIMEOUT_SECONDS` / `COMMAND_ACK_TIMEOUT_SECONDS` / `WEATHER_INTERVAL_SECONDS` 共 4 个，见第 2 节。

### 9.3 响应体新增字段（裁定：接受，均为增量）
- `POST /api/command/execute` → 增 `published`(bool)、`detail`(string)
- `POST /api/reasoning/simulate` → 增 `corrected`(bool)、`prior`(object)
- 二者均**只增不改**，V1 既有字段逐字未动。

### 9.4 `/api/meta` 的"扩展"（裁定：接受）
AC8 要求 V1 接口逐字段不变，但 `/api/meta` 被 V2_PLAN §6 明确列为"扩展"接口 → 该接口按**超集**验收：V1 字段（`plots[].plot_code/plot_name/devices`、`thresholds`、`sim_interval_seconds`）逐字保留，另增 `plots[].{name,crop,area_mu,stage,col,row}`、`crops`、`weather`。其余 10 个 V1 接口仍是严格逐字不变。

### 9.5 偏差校正同时改 `power_kwh`（裁定：接受）
大模型给出的 `yield_loss_pct` 与农学先验偏差 > `REASONING_PRIOR_TOLERANCE_PCT`(15) 时，后端**同时**把 `power_kwh` 也换成先验值，避免同一棵树里两个数字出自不同模型而自相矛盾。响应体 `corrected=true` 且白盒第 3 步写明校正原因。

### 9.6 V2.0 新增接口 / 表 / MQTT 主题的权威来源

本文件 §2–§8 冻结的是 **V1 的 11 个接口与 4 张表**，V2.0 的全部增量（12 条新接口的逐字段响应体、4 张新表 DDL、3 条新 MQTT 主题）**不再复制到本文件**，避免同一事实两处维护而漂移。权威来源如下：

| 内容 | 权威文件 |
|---|---|
| 12 条 V2 新接口的逐字段响应体与示例 | `docs/API.md` |
| 4 张新表（`reasoning` / `commands` / `weather` / `skus`）DDL 与索引 | `docs/ARCHITECTURE.md` 第二章 |
| MQTT 新主题 `agri/weather/{plot_code}`、`agri/command/{plot}/{device}`、`agri/command_ack/{plot}/{device}` | `docs/ARCHITECTURE.md` 第四章 |
| 推演树 JSON 冻结结构、Prompt 全文、三段式降级 | `docs/V2_PLAN.md` §7 / §8 |
| V1 的 11 个接口 | **本文件 §5（仍严格冻结，V2 只增不改）** |

> 唯一例外是 §9.4 已裁定的 `/api/meta`：该接口按**超集**验收。

## 10. V2.1 契约修订记录（调度方裁定，2026-11-04）

针对 `01_数据与模拟改进清单.md`（ClawsGo 提出）的逐条核实结论，调度方冻结以下 5 项变更。实现位置与验收标准见 `docs/V2_PLAN.md`。

### 10.1 C-1 灌溉物理：真实速率 × 显式演示加速
模拟器不再有"自动灌溉脉冲"。灌溉只有一个入口：下行指令 `irrigation_on`。
- 真实速率常量 `SIM_IRRIGATION_RATE_PCT_PER_S=0.008`（%/秒，即 28.8 点/小时）
- 演示加速 `SIM_DEMO_ACCELERATION=30`（设 1 即完全真实时间）
- 生效速率 = 0.008 × 30 = 0.24 %/真实秒 → 演示中 30 秒可见约 +7 点
- `duration_min` 是**模拟分钟**，真实开闸时长 = `duration_min × 60 / SIM_DEMO_ACCELERATION`
- `backend/app/knowledge.py` 的 `duration_min` 与 `delta` 必须与模拟器共用同一常量，误差 ≤ 1 点

### 10.2 C-2 土壤蒸散：日失水 3~6 点
`SoilPhysics.step()` 是土壤墒情的唯一推进入口，水源只有降雨与灌溉，蒸散是唯一失水项且降雨期间归零。
- `ET_BASE_PCT_PER_H=0.19`，按气温与相对湿度修正（`ET_TEMP_COEFF=0.04`、`ET_HUMIDITY_COEFF=0.5`）
- 降雨按湿润层 55% 入渗；`rain_mm` 由气象模块按**真实时间**给出，土壤侧不得二次放大
- 相对偏移 `drift` 同时受输出区间钳制，墒情不允许越过 `[SOIL_MOISTURE_FLOOR, SOIL_MOISTURE_CEIL]`

### 10.3 C-3 气象：单场 5~60 分钟、24h 累计 ≤ 40mm
- `RAIN_EVENT_MIN_MINUTES=5` / `RAIN_EVENT_MAX_MINUTES=60` / `RAIN_INTENSITY_MIN_MM_H=0.5` / `RAIN_INTENSITY_MAX_MM_H=8`
- 单场雨量 ≤ `RAIN_EVENT_MAX_MM=25`；24 小时窗口累计 ≤ `RAIN_24H_MAX_MM=40`（启动新雨时按剩余额度夹紧）
- 雨强按月份系数（`MONTH_RAIN_FACTOR`）与小时系数调制，风向做随机游走平滑（不再整点跳变）

### 10.4 C-4 告警抑制：连续采样 + 温度前置
- 新增 `ALERT_SUSTAINED_SAMPLES=3`（同一设备同一指标连续 3 个采样越界才告警）
- 新增 `HUMIDITY_ALERT_MIN_TEMPERATURE=20.0`（湿度告警需最近一次气温 ≥ 20℃）
- 湿度正常区上限 85 → 92，critical 上限 95 → 97（详见 §6）

### 10.5 C-5 脏值默认关闭，改用连续场景
- `SIM_BAD_PROBABILITY` 默认 `0.12` → `0`：默认不再注入单点越界脏值。设 >0 时行为与 v1.1 相同（仅在注入时 payload 打 `injected` 标记）。
- 新增 `SIM_SCENARIO`：`normal`(默认) | `drought` | `heat` | `disease` | `cold`，是**连续过程**而非单点注入，各场景时长见 `SCENARIO_HOURS`。
- payload 新增 `sim_acceleration` 与 `scenario` 两个字段（增量，不破坏 V1 字段）。

### 10.6 实现边界（不在本次修订内）
清单中属"农学口径与推演模型"的条目**已于 V2.1 第二步全部处理**，逐条结论见 §11。

## 11. V2.1 第二步契约修订记录（调度方裁定，2026-11-04）

第一步交付后，调度方对 `01_数据与模拟改进清单.md` 中「农学口径与推演模型」的剩余条目逐条核实，
并结合 `scripts/seed_history.py` 不支持 C 区与 co2 的缺陷，冻结以下 12 项。**全部已落到源码并通过端到端复验。**

### 11.1 C-10 温室 CO₂ 全链路
- 新增设备 `FJ-MUSH-C01`（C区温室环境站，C 区·闽宁协作温室菇棚，香菇，1.2 亩，出菇期）。
- `telemetry` 表新增列 `co2 REAL`；老库由 `db.py:_ensure_columns()` 用 `PRAGMA table_info` 检查后 `ALTER TABLE` 幂等补列（L178-188）。
- `config.DEVICE_METRICS`（env→temperature,humidity；soil→soil_moisture,soil_temp）+ `GREENHOUSE_EXTRA_METRICS=("co2",)`：**同地块两类设备各报各的指标，绝不混算**。
- `GET /api/telemetry/history` 增可选 `metric` 参数（见 §5）；`/api/telemetry/summary` 增 `co2` 段（仅当窗口内有 co2 采样）。
- 非温室设备的 co2 恒为 null（不是 0），前端据此隐藏 CO₂ 卡。

### 11.2 设备形态差异化（C-8）
`FJ-CITRUS-A01`=[temperature,humidity,battery]、`FJ-CITRUS-A02`=[soil_moisture,soil_temp,battery]、
`FJ-CITRUS-B01`=[temperature,humidity,battery]、`FJ-CITRUS-B02`=[soil_moisture,soil_temp,battery]、
`FJ-MUSH-C01`=[temperature,humidity,co2,battery]。`/api/devices` 的 `latest` 会带 null 列，消费方必须过滤 null。

### 11.3 湿度告警升级为长时病害风险（C-12）
见 §6 第三条抑制规则。`HUMIDITY_RISK_MIN_HOURS=6.0`、`HUMIDITY_RISK_TEMP_MIN=20.0`、`HUMIDITY_RISK_TEMP_MAX=28.0`、
`HUMIDITY_RISK_WINDOW_HOURS=24.0`。炭疽病处置由「施药 60ml」改为**风险提示 + 48h 内喷施保护性杀菌剂**，剂量不写死。

### 11.4 墒情阈值按土壤质地分档（C-11）
`SOIL_TEXTURE_THRESHOLDS`：砂壤 `{28,80,20}`、壤土 `{35,80,25}`、黏壤 `{40,80,30}`；`DEFAULT_SOIL_TEXTURE="壤土"`。
地块在 `config.PLOTS` 里标注 `soil_texture`（A 壤土 / B 砂壤 / C 无墒情设备）。`/api/meta` 与 `knowledge.py` 取同一函数 `config.meta_thresholds(plot_code)`。

### 11.5 温度下限 15℃ → 5℃（C-12）
`THRESHOLDS["temperature"]` 变为 `{min 5.0, max 35.0, critical_min 0.0, critical_max 38.0}`。柑橘低温胁迫阈值是 5℃，0℃ 以下才是冻害 critical。

### 11.6 耗电口径改为每立方米（C-6）
废弃 `POWER_KWH_PER_MU`（按亩均拍脑袋，与灌溉时长无关）。改为水量平衡：
根层湿润区亏缺水量 → 系统流量 → 时长 → 耗电，常量 `KWH_PER_M3=0.15`（低扬程滴灌合理区间 0.12~0.18）。
`IRRIGATION_MAX_MINUTES=1440`（24h 上限）。`knowledge.py` 与 `simulator/mock_sensor.py` **共用同一常量**，误差 ≤ 1 点。

### 11.7 减产率连续化（C-11）
废弃「低于下限即 15% 下限」的跳变。改为 `severity = depth^1.5 × duration_factor`，`loss = YIELD_LOSS_MAX_PCT × severity`，
无 15% 下限；`duration_factor` 分母由 24h 改为 **72h**（`knowledge.py:53`）；墒情达正常下限即 0。

### 11.8 露天园不再出通风方案（C-11）
`ventilation_on` 只在 `scenario == "greenhouse"` 时产出；露天园高温改滴灌降温 / 树盘覆盖。
C 区温室菇棚兜底动作是「通风换气 15 分钟」（棚内不做墒情灌溉决策）。

### 11.9 未知地块/设备不再编造默认值（C-9）
`knowledge`/`reasoning` 对未知 `plot_code` 返回 `None` 或抛错，由路由层转成 **404** `{"detail":"plot not found"}`；
未知 `device_code` → **422** `{"detail":"device not found"}`。绝不对不存在的对象「假装下发成功」。

### 11.10 物候期按当前月份推导（C-7）
地块不再写死 `stage`，改为 `stage_cycle` 六段窗口 + `config.stage_for(plot_code)` 按 `MM-DD` 推导；
`stage_window` 标记该地块当季窗口。品种按产地据实：A 柑橘(芦柑)、B 柑橘(南丰蜜桔)、C 香菇；**旧稿的沃柑/沙糖桔与福建南平产地不符，已删**。

### 11.11 数据缺失演示（C-10）
新增 `SIM_PACKET_LOSS`（默认 `0`，建议演示值 0.05~0.2）：按概率**整条丢弃**遥测，前端曲线出现断点。
与 `SIM_BAD_PROBABILITY`（单点越界，默认 0）语义不同，二者互不替代。环境变量总数 **28 → 29**。

### 11.12 `scripts/seed_history.py` 支持 C 区与 co2（调度方修复）
原脚本 `BASELINE` 只含 4 台柑橘设备且每台固定写 5 列 → C 区从未进历史、co2 列恒 NULL，且环境站在历史里带了 soil_moisture。
现按设备真实形态拆键：A01/B01 只写 temperature+humidity+battery，A02/B02 只写 soil_moisture+soil_temp+battery，
`FJ-MUSH-C01` 写 temperature+humidity+**co2**+battery；co2 走日周期（夜间高、午后低）；
`--bad-probability` 缺省取 `config.SIM_BAD_PROBABILITY`（不再是硬编码 0.03）。实测 `--hours 6 --step-minutes 30` → 65 行 / 5 台设备各 13 点 / C01 co2=13。
