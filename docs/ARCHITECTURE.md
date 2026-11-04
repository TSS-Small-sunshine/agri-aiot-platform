# 目录结构与数据库设计

> 本文是**设计文档**，用于交付说明与答辩讲解：给出项目目录结构、SQLite 数据库设计、告警阈值规则、MQTT 主题约定、REST 接口清单与环境变量。
> **实现细节以 [docs/CONTRACT.md](CONTRACT.md)（冻结版契约，唯一真相）与源码为准**；本文若与二者不一致，以后者为准。
> 目录树已与仓库受版本控制的 **83 个文件**（`git ls-files`）双向对齐；8 张表的 DDL 已与 `backend/app/db.py` 的 DDL 常量做空白归一后逐字比对（identical: True）。

## 一、项目目录结构

```
agri-aiot-platform/
├── .github/
│   └── workflows/
│       └── build-push.yml            # CI：多阶段构建 backend / simulator 镜像 → 推 ghcr.io
├── backend/                          # 【后端】FastAPI + SQLite(WAL)
│   ├── app/
│   │   ├── __init__.py               # 包标记
│   │   ├── main.py                   # 应用入口：lifespan 建表 / 路由注册 / StaticFiles + SPA 回退 / 指令超时扫描
│   │   ├── config.py                 # 全部配置从环境变量读；含阈值、设备清单、V2 主题与农学先验口径
│   │   ├── db.py                     # SQLite 连接、WAL、幂等建表（V1 DDL + V2 DDL）、读写助手
│   │   ├── schemas.py                # Pydantic 响应模型（字段与契约第 5 节 / API.md 逐字段一致）
│   │   ├── timeutil.py               # 时间助手：全系统统一 ISO8601 带时区
│   │   ├── alerts.py                 # 阈值规则引擎（契约第 6 节）+ 告警冷却去重
│   │   ├── mqtt_client.py            # 订阅遥测/气象/指令回执 → 落库 → 触发告警评估与指令状态流转
│   │   ├── llm.py                    # 大模型调用：超时 / 重试 / Mock 降级 / latency 埋点
│   │   ├── runtime_config.py         # V2 运行时配置中心：runtime_config.json 读写 + Key 掩码 + 优先级解析
│   │   ├── knowledge.py              # V2 农学先验规则引擎（不依赖大模型、纯函数；降级与交叉校验共用）
│   │   ├── reasoning.py              # V2 因果推演：Context 组装 → Prompt → LLM → Schema 校验 → 交叉校验 → 三段式降级
│   │   ├── command.py                # V2 指令闭环：下发 / 回执状态流转 / 超时清扫
│   │   ├── weather.py                # V2 气象：最新观测 + 以观测为锚点的确定性 24h 预报
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── devices.py            # GET /api/devices
│   │   │   ├── telemetry.py          # GET /api/telemetry/latest | history | summary
│   │   │   ├── alerts.py             # GET /api/alerts、POST /api/alerts/{id}/ack
│   │   │   ├── ai.py                 # GET /api/ai/models、POST /api/ai/chat、GET /api/ai/history
│   │   │   ├── meta.py               # GET /api/meta（地块/作物/阈值/气象段）
│   │   │   ├── config.py             # V2：GET|PUT /api/config、POST /api/config/test、GET /api/models
│   │   │   ├── reasoning.py          # V2：POST /api/reasoning/simulate、GET /api/reasoning/history | {id}
│   │   │   ├── command.py            # V2：POST /api/command/execute、GET /api/command/history
│   │   │   ├── weather.py            # V2：GET /api/weather/latest
│   │   │   └── shop.py               # V2：GET /api/shop/skus
│   │   └── static/                   # 前端构建产物落点（gitignore，由脚本或镜像填入）
│   ├── requirements.txt              # fastapi / uvicorn / paho-mqtt / httpx / pydantic
│   └── Dockerfile                    # 多阶段：node 构建前端 → python:3.12-slim 运行
├── frontend/                         # 【前端】Vue3 + Vite
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.js                # build.outDir = dist；dev 代理 /api → 127.0.0.1:8000
│   └── src/
│       ├── main.js                   # 挂载根组件
│       ├── App.vue                   # 根组件：按 route.path 分发 MainView / LegacyView / MobileView
│       ├── api.js                    # 统一请求封装（超时 + ApiError）
│       ├── config.js                 # 前端可调参数与路由表（VITE_*，带安全默认值）
│       ├── router.js                 # V2 手写极简路由（/、/legacy、/mobile），未命中回落 /
│       ├── sourceLabel.js            # V2 三段式降级角标唯一判定处
│       ├── toast.js                  # V2 轻量 Toast 状态
│       ├── echarts.js                # ECharts 按需引入
│       ├── styles/
│       │   └── theme.css             # 深色科技感主题（颜色/间距走 CSS 变量）
│       ├── components/
│       │   ├── RealtimeChart.vue     # 温湿度折线（5s 刷新）
│       │   ├── DeviceStatusCard.vue  # 设备在线状态（绿/红点）
│       │   ├── SoilGauge.vue         # 墒情仪表
│       │   ├── AlertPanel.vue        # 告警红色面板
│       │   ├── PlotMap.vue           # V1 多地块点位图
│       │   ├── AiChat.vue            # AI 对话 + 模型下拉 + 历史侧栏
│       │   ├── PlotGrid25D.vue       # V2 2.5D 地块网格（作物 / 面积 / 物候期）
│       │   ├── ReasoningTree.vue     # V2 因果推演树（ECharts graph + 撑边节点防裁切）
│       │   ├── ReasoningWhitebox.vue # V2 白盒时间轴（样本条数与规则命中）
│       │   ├── CommandButton.vue     # V2 指令下发按钮 + 状态角标
│       │   ├── SkuCard.vue           # V2 农资 SKU 卡片
│       │   ├── SettingsModal.vue     # V2 配置中心弹窗（Base URL / API Key / 模型）
│       │   ├── ToastHost.vue         # V2 Toast 宿主
│       │   ├── AccessiblePanel.vue   # V2 大字模式面板
│       │   └── MobileShell.vue       # V2 移动端外壳
│       └── views/
│           ├── MainView.vue          # V2 主大屏（KPI + 2.5D 地块 + 推演树 + AI 双轨）
│           ├── LegacyView.vue        # /legacy：V1 大屏作用域包装
│           ├── MobileView.vue        # /mobile：移动端视图
│           └── V1Screen.vue          # V1 原大屏（六格布局）
├── simulator/
│   ├── mock_sensor.py                # MQTT 模拟器：4 台设备遥测 + 气象上报 + 指令执行与回执
│   ├── weather.py                    # V2 模拟器侧气象数据生成
│   ├── requirements.txt              # 仅 paho-mqtt
│   └── Dockerfile
├── mosquitto/
│   └── mosquitto.conf                # broker 配置（仅内网，不映射宿主机端口）
├── scripts/
│   ├── dev_up.sh                     # 裸机一键启动（Linux / macOS）
│   ├── dev_up.ps1                    # 裸机一键启动（Windows）
│   └── seed_history.py               # 灌入过去 N 小时历史遥测，让演示立刻有曲线
├── docs/
│   ├── CONTRACT.md                   # 接口契约（冻结版，唯一真相）
│   ├── ARCHITECTURE.md               # 本文件：目录结构 + 数据库设计 + 阈值 + MQTT + 接口 + 环境变量
│   ├── API.md                        # 接口文档（22 条：方法 / 参数 / 示例请求 / 示例响应）
│   ├── V2_PLAN.md                    # V2.0 实施方案（规划稿）
│   ├── V2_PITCH.md                   # 答辩与演讲口径
│   ├── SPEECH_3MIN.md                # 3 分钟逐字稿 + 数字速查卡
│   ├── PROJECT_AUDIT.md              # 生产环境实测审计报告
│   ├── CAREER_PLAN.md                # 职业规划大赛《生涯发展报告》（成长赛道）
├── docker-compose.yml                # 默认：拉 ghcr 预构建镜像，一键起三容器
├── docker-compose.build.yml          # 可选覆盖文件：本地 build 而非拉镜像
├── .dockerignore                     # 构建上下文排除（.venv / node_modules / dist / data / .env …）
├── .env.example                      # 全部 25 个环境变量 + 中文注释
├── .gitignore
├── README.md                         # 部署与运维保姆级文档
└── CHANGELOG.md                      # 更新日志 + 技术难点与解决思路
```

> `backend/app/static/`、`data/`、`logs/`、`.env`、`*.db*` 均在 `.gitignore` 中，由脚本或容器在运行时生成，不入库。

## 二、数据库设计（SQLite，WAL 模式）

### 2.1 建表 DDL

源码位置：`backend/app/db.py` 的两个 DDL 常量 —— V1 段 `DDL`（L15-40，契约第 4 节逐字照抄）、V2 段 `DDL_V2`（L43-92，V2_PLAN 第 3 节原文）。应用启动时（`main.py` 的 lifespan → `db.init_db()`，见 `db.py:178-185`）用 `executescript` 依次幂等执行两段。

#### V1 段：4 张表 + 4 个索引

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

#### V2.0 段：4 张新表 + 3 个新索引

```sql
CREATE TABLE IF NOT EXISTS reasoning (
  id          TEXT PRIMARY KEY,
  plot_code   TEXT NOT NULL,
  trigger     TEXT,
  prompt      TEXT NOT NULL,
  result      TEXT NOT NULL,
  source      TEXT NOT NULL,
  model       TEXT,
  latency_ms  INTEGER,
  error       TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reasoning_created ON reasoning(created_at DESC);
CREATE TABLE IF NOT EXISTS commands (
  id           TEXT PRIMARY KEY,
  reasoning_id TEXT,
  plot_code    TEXT NOT NULL,
  device_code  TEXT NOT NULL,
  node_id      TEXT,
  action       TEXT NOT NULL,
  params       TEXT,
  topic        TEXT NOT NULL,
  payload      TEXT NOT NULL,
  status       TEXT NOT NULL,
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
  image       TEXT,
  stock       INTEGER,
  description TEXT,
  keywords    TEXT
);
```

### 2.2 表与字段说明

#### devices —— 设备台账

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | 自增主键 |
| device_code | TEXT UNIQUE NOT NULL | 设备编号，如 `FJ-CITRUS-A01` |
| name | TEXT NOT NULL | 设备名，如「A区柑橘园环境站」 |
| plot_code | TEXT NOT NULL | 地块编号 `A` / `B`（点位图分组用） |
| plot_name | TEXT | 地块名，如「A区·柑橘示范园」 |
| type | TEXT NOT NULL | `env`（温湿度）/ `soil`（墒情） |
| location | TEXT | 部署位置描述 |
| status | TEXT DEFAULT 'online' | `online` / `offline`，由 `last_seen` 与 `DEVICE_OFFLINE_SECONDS` 推导 |
| last_seen | TEXT | 最后上报时间 ISO8601（收到消息时 `touch_device()` 刷新） |
| created_at | TEXT NOT NULL | 首次入库时间 |

启动时由 `seed_devices()` 按契约第 3 节幂等写入 4 台设备（`ON CONFLICT(device_code) DO UPDATE`，不覆盖 `last_seen`）。

#### telemetry —— 传感器遥测

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | 自增主键 |
| device_code | TEXT NOT NULL | 关联 `devices.device_code` |
| ts | TEXT NOT NULL | 采集时间 ISO8601（建索引） |
| temperature | REAL | 空气温度 ℃ |
| humidity | REAL | 空气湿度 % |
| soil_moisture | REAL | 土壤墒情 % |
| soil_temp | REAL | 土壤温度 ℃ |
| battery | REAL | 电量 %（模拟值） |
| raw | TEXT | 原始 MQTT JSON 报文，便于回溯 |

#### ai_chat —— AI 对话记录

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | 自增主键 |
| session_id | TEXT | 会话分组（前端传入，可空） |
| question | TEXT NOT NULL | 用户提问 |
| answer | TEXT | 模型回答（降级时写 Mock 答案） |
| model | TEXT | 实际使用的模型 id |
| degraded | INTEGER DEFAULT 0 | 1 = 降级返回 Mock |
| latency_ms | INTEGER | 端到端耗时，超时治理埋点 |
| prompt_tokens | INTEGER | 用量（上游未返回则 NULL） |
| completion_tokens | INTEGER | 用量（上游未返回则 NULL） |
| created_at | TEXT NOT NULL | 写入时间 ISO8601 |

#### alerts —— 阈值告警

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | 自增主键 |
| device_code | TEXT NOT NULL | 触发设备 |
| metric | TEXT NOT NULL | `temperature` / `humidity` / `soil_moisture` |
| value | REAL | 触发值 |
| threshold | REAL | 被突破的阈值 |
| level | TEXT | `warning` / `critical` |
| message | TEXT | 中文告警文案 |
| acked | INTEGER DEFAULT 0 | 1 = 已确认（POST /api/alerts/{id}/ack） |
| created_at | TEXT NOT NULL | 触发时间 ISO8601 |

#### reasoning —— 推演结论（V2.0 新增）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | 推演编号 `rs_{时间戳}_{4位hex}`，同时是 `GET /api/reasoning/{id}` 的主键 |
| plot_code | TEXT NOT NULL | 地块编号 |
| trigger | TEXT | 触发来源（如手动发起） |
| prompt | TEXT NOT NULL | 实际发给大模型的完整 Prompt 原文（System + User），是白盒证据 |
| result | TEXT NOT NULL | 结论 JSON（含 tree / whitebox / summary / yield_loss_pct / power_kwh 等） |
| source | TEXT NOT NULL | `primary`（主模型）/ `fallback`（本地农学先验降级） |
| model | TEXT | 实际使用的模型名；降级时为 `local-agronomy-rules` |
| latency_ms | INTEGER | 端到端耗时 |
| error | TEXT | 降级/失败原因（成功时为 NULL） |
| created_at | TEXT NOT NULL | 生成时间 ISO8601 |

#### commands —— 指令闭环（V2.0 新增）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | 指令编号 `cmd_{时间戳}_{4位hex}` |
| reasoning_id | TEXT | 关联的推演编号（可由推演直接下发，可空） |
| plot_code | TEXT NOT NULL | 地块编号 |
| device_code | TEXT NOT NULL | 目标设备 |
| node_id | TEXT | 推演树节点 id（可空） |
| action | TEXT NOT NULL | 动作白名单之一：`irrigation_on` / `irrigation_off` / `pesticide_dose` / `ventilation_on` |
| params | TEXT | 动作参数 JSON 字符串（如 `{"duration_min": 40}`） |
| topic | TEXT NOT NULL | 实际下发的 MQTT 主题 |
| payload | TEXT NOT NULL | 实际下发的报文 JSON 字符串 |
| status | TEXT NOT NULL | 状态机 `dispatched` → `executed` / `failed` / `timeout` |
| ack_at | TEXT | 回执到达时间（未回执为 NULL） |
| created_at | TEXT NOT NULL | 下发时间 ISO8601 |

#### weather —— 气象观测（V2.0 新增）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | 自增主键 |
| plot_code | TEXT NOT NULL | 地块编号 |
| ts | TEXT NOT NULL | 观测时间 ISO8601 |
| temperature | REAL | 气温 ℃ |
| humidity | REAL | 相对湿度 % |
| rainfall_mm | REAL | 降水量 mm |
| wind_dir | TEXT | 风向（八方位中文） |
| wind_level | INTEGER | 风力等级 |
| condition | TEXT | 天气现象（晴 / 阴 / 小雨 / 中雨） |

表级约束 `UNIQUE(plot_code, ts)` 配合 `INSERT OR REPLACE` 写入，使同一地块同一时刻的气象幂等覆盖。

#### skus —— 农资商品（V2.0 新增）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | 商品编号，如 `sku-drip-tape` |
| name | TEXT NOT NULL | 商品名 |
| category | TEXT | 品类（肥料 / 灌溉 / 植保 / 设备 / 土壤调理） |
| price | REAL | 单价 |
| unit | TEXT | 计价单位，如「卷(1000m)」 |
| image | TEXT | 图标标识符；前端用本地占位块渲染，**不依赖外网图片** |
| stock | INTEGER | 库存 |
| description | TEXT | 一句话说明 |
| keywords | TEXT | 关键词（供推演节点的 `sku_keywords` 与模糊检索命中） |

启动时由 `seed_skus()` 幂等写入 6 条（`INSERT OR IGNORE`，绝不覆盖用户改动）。

### 2.3 索引（共 7 个）

| 索引名 | 表 | 定义 | 用途 |
|---|---|---|---|
| idx_telemetry_device_ts | telemetry | (device_code, ts) | 单设备时序曲线查询 |
| idx_telemetry_ts | telemetry | (ts) | 全局聚合（summary）与保留期清理 |
| idx_ai_chat_created | ai_chat | (created_at DESC) | 对话历史倒序取最近 N 条 |
| idx_alerts_created | alerts | (created_at DESC) | 告警列表倒序取最近 N 条 |
| idx_reasoning_created | reasoning | (created_at DESC) | 推演历史倒序取最近 N 条 |
| idx_commands_created | commands | (created_at DESC) | 指令历史倒序取最近 N 条 + 超时清扫 |
| idx_weather_plot_ts | weather | (plot_code, ts DESC) | 单地块最新气象与最近序列 |

> `weather` 表另有建表语句内联的 `UNIQUE(plot_code, ts)` 隐式唯一索引，不属于上表的 7 个显式索引。

### 2.4 连接与并发策略（backend/app/db.py）

- **写入**：全局单例连接 + 一把可重入锁 `threading.RLock`，MQTT 线程与 HTTP 线程共用，序列化写者。
- **读取**：`threading.local` 连接，按线程隔离。
- **PRAGMA**：`journal_mode=WAL`、`synchronous=NORMAL`、`busy_timeout=30000`、`foreign_keys=ON`。
- 该组合让读写并行，规避 `database is locked`。
- **保留期**：启动时 `purge_old_telemetry()` 按 `TELEMETRY_RETENTION_DAYS` 删除过期遥测。
- **时间字段**：一律 ISO8601 带时区字符串（`timeutil.now_iso()`），字符串序即时间序。
- **V2 状态流转**：`commands` 的回执只在 `status='dispatched'` 时流转（`db.py:328-348`），避免乱序回执覆盖终态；超时清扫由 `main.py` 的 `_command_timeout_sweeper` 后台任务按 `COMMAND_ACK_TIMEOUT_SECONDS` 触发。

## 三、告警阈值规则

定义在 `backend/app/config.py` 的 `THRESHOLDS` 常量（L117-121），由 `backend/app/alerts.py` 执行判定，并经 `GET /api/meta` 的 `thresholds` 字段暴露给前端。

| 指标 | 正常区间 | warning | critical |
|---|---|---|---|
| temperature | 15~35 ℃ | 35~38 或 5~15 | > 38 或 < 5 |
| humidity | 40~85 % | < 40 或 > 85 | < 30 或 > 95 |
| soil_moisture | 35~80 % | < 35 | < 25 |

字段取值（与源码逐字一致）：

- `temperature`：`min 15.0`、`max 35.0`、`critical_min 5.0`、`critical_max 38.0`。
- `humidity`：`min 40.0`、`max 85.0`、`critical_min 30.0`、`critical_max 95.0`。
- `soil_moisture`：`min 35.0`、`max 80.0`、`critical_min 25.0`（无上限档）。

- **humidity 为对称双档**，不留 30~40 / 85~95 的静默带（`alerts.py` 的 `evaluate_humidity` 先判 critical 再判 warning）。
- **设备离线判定**：`last_seen` 距今 > `DEVICE_OFFLINE_SECONDS`（默认 30 秒）即 `offline`。
- **告警冷却**：同一 `device_code + metric + level` 在 `ALERT_COOLDOWN_SECONDS`（默认 300 秒）内不重复写表，避免 5 秒高频上报刷爆 `alerts`。

## 四、MQTT 主题约定

### 4.1 主题清单与链路

| 方向 | 主题 | QoS | 说明 |
|---|---|---|---|
| 上行 | `agri/telemetry/{plot_code}/{device_code}` | 0 | 设备遥测（V1） |
| 上行 | `agri/weather/{plot_code}` | 0 | 气象观测（V2 新增） |
| 下行 | `agri/command/{plot_code}/{device_code}` | **1** | 后端下发指令（V2 新增） |
| 上行 | `agri/command_ack/{plot_code}/{device_code}` | **1** | 模拟器执行回执（V2 新增） |

```
simulator（4 台设备 + 气象 Mock + 指令执行）
  │
  ├── ① 上行 QoS 0   agri/telemetry/{plot_code}/{device_code}    ──▶  mosquitto
  ├── ② 上行 QoS 0   agri/weather/{plot_code}                    ──▶  mosquitto
  ├── ③ 上行 QoS 1   agri/command_ack/{plot_code}/{device_code}  ──▶  mosquitto
  └── ④ 下行 QoS 1   agri/command/{plot_code}/{device_code}      ◀──  mosquitto
                                                                       │
                                                      订阅（MQTT_TOPIC）│
                                                                       ▼
                                                    backend（FastAPI + SQLite/WAL）
```

- **订阅侧**：`MQTT_TOPIC=agri/telemetry/+/+`（后端与模拟器读同一变量）；V2 主题名是契约的一部分，写在 `config.py:156-159`，**不开放为环境变量**。
- **QoS 0，非保留消息**（避免离线设备假在线）；指令与回执用 **QoS 1** 保证至少送达一次。

### 4.2 payload 示例

遥测上行：

```json
{"device_code":"FJ-CITRUS-A01","plot_code":"A","type":"env",
 "ts":"2026-01-01T12:00:00+08:00","temperature":26.4,"humidity":68.2,
 "soil_moisture":52.1,"soil_temp":22.7,"battery":93.5}
```

气象上行（`agri/weather/{plot_code}`）：

```json
{"plot_code":"A","ts":"2026-11-02T11:42:11+08:00","temperature":26.4,
 "humidity":68.2,"rainfall_mm":0.0,"wind_dir":"东南","wind_level":2,
 "condition":"晴"}
```

指令下行（`agri/command/{plot_code}/{device_code}`，QoS 1）：

```json
{"command_id":"cmd_20261102T194844_299d","action":"irrigation_on",
 "params":{"duration_min":40},"issued_at":"2026-11-02T19:48:44+08:00"}
```

回执上行（`agri/command_ack/{plot_code}/{device_code}`，QoS 1）：

```json
{"command_id":"cmd_20261102T194844_299d","status":"executed",
 "detail":"已开启滴灌 40 分钟","ts":"2026-11-02T19:48:46+08:00"}
```

### 4.3 设备清单

设备清单（`config.py` 的 `DEVICES` 与 `simulator/mock_sensor.py` 必须一致）：

| device_code | name | plot_code | plot_name | type |
|---|---|---|---|---|
| FJ-CITRUS-A01 | A区柑橘园环境站 | A | A区·柑橘示范园 | env |
| FJ-CITRUS-A02 | A区柑橘园墒情站 | A | A区·柑橘示范园 | soil |
| FJ-CITRUS-B01 | B区柑橘园环境站 | B | B区·柑橘试验园 | env |
| FJ-CITRUS-B02 | B区柑橘园墒情站 | B | B区·柑橘试验园 | soil |

## 五、REST 接口清单（共 22 条）

统一前缀 `/api`；错误一律 FastAPI 标准 `{"detail": "..."}`。逐字段响应体见 [API.md](API.md) 与契约第 5 节。

### 5.1 V1 基础能力（11 条）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/health | 健康检查（db / mqtt / llm 状态） |
| GET | /api/devices | 设备列表 + 在线状态 + 最新一条遥测 |
| GET | /api/telemetry/latest | 各设备最新一条 |
| GET | /api/telemetry/history | 单设备时序曲线（device_code / hours / limit） |
| GET | /api/telemetry/summary | 均值/极值（大屏 KPI 卡，hours） |
| GET | /api/alerts | 告警列表（limit / only_unacked） |
| POST | /api/alerts/{id}/ack | 确认告警 |
| GET | /api/ai/models | 可用模型列表（无 Key 返回 mock 列表） |
| POST | /api/ai/chat | 提问 → 回答（超时/异常自动降级 Mock） |
| GET | /api/ai/history | AI 对话历史（侧栏） |
| GET | /api/meta | 地块分组 + 作物 + 阈值 + 气象段 + 轮询间隔（V2 起为 V1 字段的超集） |

### 5.2 V2.0 决策中枢（11 条）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/config | 当前生效配置（`api_key` 只回显掩码） |
| PUT | /api/config | 写运行时配置并**立即热生效**（无需重启容器） |
| POST | /api/config/test | 探活 `/models` 并实测所选模型可调用性（`model_ok`），失败也返回 200 + `ok=false` |
| GET | /api/models | 运行时模型列表（与 `GET /api/ai/models` 同源同结构，后者保留为别名） |
| POST | /api/reasoning/simulate | 因果推演（三段式降级，**永不 5xx**） |
| GET | /api/reasoning/history | 推演历史摘要（主键字段为 `reasoning_id`，不含完整 prompt） |
| GET | /api/reasoning/{id} | 单次推演详情（额外含 `prompt` 与 `raw_response`） |
| POST | /api/command/execute | 下发指令（落库 `dispatched` + MQTT QoS 1） |
| GET | /api/command/history | 指令历史与状态流转 |
| GET | /api/weather/latest | 最新气象 + 未来 24h 预报（无数据也 200） |
| GET | /api/shop/skus | 农资 SKU 列表（`keyword` 模糊匹配） |

> 源码侧：10 个 router 共 **21** 处路由装饰器，加上 `main.py` 的 3 处 —— `GET /api/health`（计入契约）与 `GET /`、`GET /{full_path:path}`（静态托管兜底，`include_in_schema=False`，不计入契约），合计 24 处装饰器、**22 条接口**。

## 六、环境变量（共 25 个）

全部 25 个可调参数见仓库根 `.env.example`（含中文注释与默认值），代码只从环境变量读取，零硬编码。名称与顺序与 `.env.example` 完全一致：

| # | 变量 | 默认值 | 说明 |
|---|---|---|---|
| 1 | APP_PORT | 8000 | 后端监听端口 |
| 2 | APP_VERSION | 2.0.0 | 版本号（`GET /api/health` 的 `version` 字段） |
| 3 | DB_PATH | /data/agri.db | SQLite 文件路径 |
| 4 | DATA_DIR | /data | 数据目录（容器内为具名卷） |
| 5 | MQTT_HOST | mosquitto | broker 地址（compose 内为服务名） |
| 6 | MQTT_PORT | 1883 | broker 端口 |
| 7 | MQTT_TOPIC | agri/telemetry/+/+ | 遥测订阅主题 |
| 8 | DEVICE_OFFLINE_SECONDS | 30 | 超过该秒数未上报判离线 |
| 9 | TELEMETRY_RETENTION_DAYS | 7 | 遥测保留天数（启动时清理） |
| 10 | HISTORY_HOURS_MAX | 168 | 历史查询最大小时数 |
| 11 | CORS_ORIGINS | * | 允许的跨域来源 |
| 12 | OPENAI_BASE_URL | （空） | 大模型接口地址（OpenAI 兼容） |
| 13 | OPENAI_API_KEY | （空） | 大模型密钥（留空即走 Mock 降级） |
| 14 | OPENAI_MODEL | （空） | 默认模型名 |
| 15 | OPENAI_TIMEOUT_SECONDS | 20 | 对话超时 |
| 16 | OPENAI_MAX_RETRIES | 1 | 对话重试次数 |
| 17 | AI_HISTORY_LIMIT | 50 | 对话历史条数上限 |
| 18 | SIM_INTERVAL_SECONDS | 5 | 模拟器遥测上报间隔 |
| 19 | SIM_DEVICES | FJ-CITRUS-A01,FJ-CITRUS-A02,FJ-CITRUS-B01,FJ-CITRUS-B02 | 模拟设备清单 |
| 20 | SIM_BAD_PROBABILITY | 0.12 | 模拟器注入越界值的概率 |
| 21 | ALERT_COOLDOWN_SECONDS | 300 | 同设备同指标同级别的告警冷却秒数 |
| 22 | RUNTIME_CONFIG_PATH | /data/runtime_config.json | 运行时配置落盘路径（含明文 Key，已 gitignore） |
| 23 | REASONING_TIMEOUT_SECONDS | 45 | 推演超时（比对话更宽） |
| 24 | COMMAND_ACK_TIMEOUT_SECONDS | 30 | 指令等回执时限，超时标 timeout |
| 25 | WEATHER_INTERVAL_SECONDS | 30 | 模拟器气象上报间隔 |

> `SIM_WEATHER_ENABLED` 不在契约的 25 个变量内：它由 `docker-compose.yml` 的 simulator 服务显式注入（源码缺省即视为开启）。

分组速览：

- 应用与数据：`APP_PORT`、`APP_VERSION`、`DB_PATH`、`DATA_DIR`、`CORS_ORIGINS`。
- MQTT 与设备：`MQTT_HOST`、`MQTT_PORT`、`MQTT_TOPIC`、`DEVICE_OFFLINE_SECONDS`。
- 保留与查询上限：`TELEMETRY_RETENTION_DAYS`、`HISTORY_HOURS_MAX`。
- 大模型：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`、`OPENAI_TIMEOUT_SECONDS`、`OPENAI_MAX_RETRIES`、`AI_HISTORY_LIMIT`。
- 模拟器与告警：`SIM_INTERVAL_SECONDS`、`SIM_DEVICES`、`SIM_BAD_PROBABILITY`、`ALERT_COOLDOWN_SECONDS`。
- V2 运行时与闭环：`RUNTIME_CONFIG_PATH`、`REASONING_TIMEOUT_SECONDS`、`COMMAND_ACK_TIMEOUT_SECONDS`、`WEATHER_INTERVAL_SECONDS`。
