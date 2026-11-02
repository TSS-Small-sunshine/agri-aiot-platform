# 接口契约（冻结版 v1）—— 三路开发必须严格遵守

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
APP_VERSION=1.0.0
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
SIM_DEVICES=FJ-CITRUS-A01,FJ-CITRUS-A02,FJ-CITRUS-B01,FJ-CITRUS-B02
SIM_BAD_PROBABILITY=0.12
ALERT_COOLDOWN_SECONDS=300
RUNTIME_CONFIG_PATH=/data/runtime_config.json
REASONING_TIMEOUT_SECONDS=45
COMMAND_ACK_TIMEOUT_SECONDS=30
WEATHER_INTERVAL_SECONDS=30
```

> 契约修订 v1.1：新增 `SIM_BAD_PROBABILITY`（模拟器越界注入概率，设 0 可关闭）与 `ALERT_COOLDOWN_SECONDS`（同 device_code+metric+level 的告警冷却秒数，防 5s 高频刷表）。
>
> 契约修订 v1.2（V2.0，共 25 个变量）：
> - `RUNTIME_CONFIG_PATH`：WebUI 配置中心落盘路径，默认 `{DATA_DIR}/runtime_config.json`。该文件保存用户在大屏齿轮弹窗里填写的 base_url / api_key / model，**优先级高于环境变量**，且不得入库（.gitignore 必须显式覆盖）。
> - `REASONING_TIMEOUT_SECONDS`：单次推演调用大模型的超时秒数，默认 45（比 `OPENAI_TIMEOUT_SECONDS` 宽，推演 prompt 更长）。
> - `COMMAND_ACK_TIMEOUT_SECONDS`：指令下发后等待模拟器回执的秒数，超时把命令标记为 `timeout`，默认 30。
> - `WEATHER_INTERVAL_SECONDS`：模拟器上报气象数据的间隔秒数，默认 30（与 5s 遥测解耦）。
>
> 配置优先级（三者取第一个有值的）：`runtime_config.json` > 环境变量 > 内置 Mock。无任何 Key 时 AI 与推演均降级为本地规则库，HTTP 仍 200。

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

**GET /api/telemetry/history** query: `device_code`(必填), `hours`(默认 1，上限 HISTORY_HOURS_MAX), `limit`(默认 720，上限 5000)
→ `{"device_code":"...","hours":1,"count":120,"points":[{"ts":"...","temperature":26.4,"humidity":68.2,"soil_moisture":52.1,"soil_temp":22.7}]}`
points 按 ts 升序。

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

**GET /api/meta** → `{"plots":[{"plot_code":"A","plot_name":"A区·柑橘示范园","devices":["FJ-CITRUS-A01","FJ-CITRUS-A02"]}],"thresholds":{"temperature":{"min":15,"max":35,"critical_min":5,"critical_max":38},"humidity":{"min":40,"max":85},"soil_moisture":{"min":35,"max":80,"critical_min":25}},"sim_interval_seconds":5}`

## 6. 告警阈值（config.py 常量，同时经 /api/meta 暴露给前端）
- temperature：正常 15~35℃；>38 或 <5 → critical；35~38 或 5~15 → warning
- humidity：正常 40~85%（无告警带）；<40 或 >85 → warning；<30 或 >95 → critical（消除原 30~40 / 85~95 的静默带）
- soil_moisture：正常 35~80%；<35 → warning；<25 → critical

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
原 `humidity` 只有 30~40 / 85~95 两段无定义 → 改为对称双档：正常 40~85；<40 或 >85 → warning；<30 或 >95 → critical。已落到 `backend/app/config.py` 的 `THRESHOLDS` 与 `/api/meta`。

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
