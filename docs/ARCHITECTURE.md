# 目录结构与数据库设计

> 本文是**设计文档**，用于交付说明与答辩讲解：给出项目目录结构、SQLite 数据库设计、告警阈值规则、MQTT 主题约定与接口清单。
> **实现细节以 [docs/CONTRACT.md](CONTRACT.md)（冻结版契约，唯一真相）与源码为准**；本文若与二者不一致，以后者为准。
> 目录树已与仓库受版本控制的 50 个文件（`git ls-files`）逐一对齐；DDL 与字段说明已逐字段核对 `backend/app/db.py`。

## 一、项目目录结构

```
agri-aiot-platform/
├── .github/
│   └── workflows/
│       └── build-push.yml            # CI：多阶段构建 backend / simulator 镜像 → 推 ghcr.io
├── backend/                          # 【后端】FastAPI + SQLite(WAL)
│   ├── app/
│   │   ├── __init__.py               # 包标记
│   │   ├── main.py                   # 应用入口：lifespan 建表 / 路由注册 / StaticFiles + SPA 回退
│   │   ├── config.py                 # 全部配置从环境变量读；含告警阈值常量与设备清单
│   │   ├── db.py                     # SQLite 连接、WAL、幂等建表、读写助手
│   │   ├── schemas.py                # Pydantic 响应模型（字段与契约第 5 节逐字段一致）
│   │   ├── timeutil.py               # 时间助手：全系统统一 ISO8601 带时区
│   │   ├── alerts.py                 # 阈值规则引擎（契约第 6 节）+ 告警冷却去重
│   │   ├── mqtt_client.py            # 订阅 MQTT → 落库 → 触发告警评估
│   │   ├── llm.py                    # 大模型调用：超时 / 重试 / Mock 降级 / latency 埋点
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── devices.py            # GET /api/devices
│   │   │   ├── telemetry.py          # GET /api/telemetry/latest | history | summary
│   │   │   ├── alerts.py             # GET /api/alerts、POST /api/alerts/{id}/ack
│   │   │   ├── ai.py                 # GET /api/ai/models、POST /api/ai/chat、GET /api/ai/history
│   │   │   └── meta.py               # GET /api/meta（地块分组 + 阈值 + 轮询间隔）
│   │   └── static/                   # 前端构建产物落点（gitignore，由脚本或镜像填入）
│   ├── requirements.txt              # fastapi / uvicorn / paho-mqtt / httpx / pydantic
│   └── Dockerfile                    # 多阶段：node 构建前端 → python:3.12-slim 运行
├── frontend/                         # 【前端】Vue3 + Vite
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.js                # build.outDir = dist；dev 代理 /api → 127.0.0.1:8000
│   └── src/
│       ├── main.js
│       ├── App.vue                   # 根组件：5s 轮询 + 顶部错误条 + 整体布局
│       ├── api.js                    # 统一请求封装（超时 + ApiError）
│       ├── config.js                 # 前端可调参数（VITE_*，带安全默认值）
│       ├── echarts.js                # ECharts 按需引入
│       ├── styles/
│       │   └── theme.css             # 深色科技感主题（颜色/间距走 CSS 变量）
│       └── components/
│           ├── RealtimeChart.vue     # 温湿度折线（5s 刷新）
│           ├── DeviceStatusCard.vue  # 设备在线状态（绿/红点）
│           ├── SoilGauge.vue         # 墒情仪表
│           ├── AlertPanel.vue        # 告警红色面板
│           ├── PlotMap.vue           # 多地块点位图
│           └── AiChat.vue            # AI 对话 + 模型下拉 + 历史侧栏
├── simulator/
│   ├── mock_sensor.py                # MQTT 模拟器：4 台设备定时上报，可注入越界值
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
│   ├── ARCHITECTURE.md               # 本文件：目录结构与数据库设计
│   └── API.md                        # 接口文档（方法/参数/示例请求/示例响应）
├── docker-compose.yml                # 默认：拉 ghcr 预构建镜像，一键起三容器
├── docker-compose.build.yml          # 可选覆盖文件：本地 build 而非拉镜像
├── .dockerignore                     # 构建上下文排除（.venv / node_modules / dist / data / .env …）
├── .env.example                      # 全部 21 个环境变量 + 中文注释
├── .gitignore
├── README.md                         # 部署与运维保姆级文档
└── CHANGELOG.md                      # 更新日志 + 技术难点与解决思路
```

> `backend/app/static/`、`data/`、`logs/`、`.env`、`*.db*` 均在 `.gitignore` 中，由脚本或容器在运行时生成，不入库。

## 二、数据库设计（SQLite，WAL 模式）

### 2.1 建表 DDL

源码位置：`backend/app/db.py` 的 `DDL` 常量；应用启动时（`main.py` 的 lifespan → `db.init_db()`）用 `executescript` 幂等执行。下列 DDL 与契约第 4 节逐字一致。

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

### 2.3 索引

| 索引名 | 表 | 定义 | 用途 |
|---|---|---|---|
| idx_telemetry_device_ts | telemetry | (device_code, ts) | 单设备时序曲线查询 |
| idx_telemetry_ts | telemetry | (ts) | 全局聚合（summary）与保留期清理 |
| idx_ai_chat_created | ai_chat | (created_at DESC) | 对话历史倒序取最近 N 条 |
| idx_alerts_created | alerts | (created_at DESC) | 告警列表倒序取最近 N 条 |

### 2.4 连接与并发策略（backend/app/db.py）

- **写入**：全局单例连接 + 一把可重入锁 `threading.RLock`，MQTT 线程与 HTTP 线程共用，序列化写者。
- **读取**：`threading.local` 连接，按线程隔离。
- **PRAGMA**：`journal_mode=WAL`、`synchronous=NORMAL`、`busy_timeout=30000`、`foreign_keys=ON`。
- 该组合让读写并行，规避 `database is locked`。
- **保留期**：启动时 `purge_old_telemetry()` 按 `TELEMETRY_RETENTION_DAYS` 删除过期遥测。
- **时间字段**：一律 ISO8601 带时区字符串（`timeutil.now_iso()`），字符串序即时间序。

## 三、告警阈值规则

定义在 `backend/app/config.py` 的 `THRESHOLDS` 常量，由 `backend/app/alerts.py` 执行判定，并经 `GET /api/meta` 的 `thresholds` 字段暴露给前端。

| 指标 | 正常区间 | warning | critical |
|---|---|---|---|
| temperature | 15~35 ℃ | 35~38 或 5~15 | > 38 或 < 5 |
| humidity | 40~85 % | < 40 或 > 85 | < 30 或 > 95 |
| soil_moisture | 35~80 % | < 35 | < 25 |

- **humidity 为对称双档**，不留 30~40 / 85~95 的静默带。
- **设备离线判定**：`last_seen` 距今 > `DEVICE_OFFLINE_SECONDS`（默认 30 秒）即 `offline`。
- **告警冷却**：同一 `device_code + metric + level` 在 `ALERT_COOLDOWN_SECONDS`（默认 300 秒）内不重复写表，避免 5 秒高频上报刷爆 `alerts`。

## 四、MQTT 主题约定

- **上报主题**：`agri/telemetry/{plot_code}/{device_code}`，例如 `agri/telemetry/A/FJ-CITRUS-A01`。
- **订阅侧**：`MQTT_TOPIC=agri/telemetry/+/+`（后端与模拟器读同一变量）。
- **QoS 0，非保留消息**（避免离线设备假在线）。

payload 为 JSON，字段与契约第 3 节一致：

```json
{"device_code":"FJ-CITRUS-A01","plot_code":"A","type":"env",
 "ts":"2026-01-01T12:00:00+08:00","temperature":26.4,"humidity":68.2,
 "soil_moisture":52.1,"soil_temp":22.7,"battery":93.5}
```

设备清单（`config.py` 的 `DEVICES` 与 `simulator/mock_sensor.py` 必须一致）：

| device_code | name | plot_code | plot_name | type |
|---|---|---|---|---|
| FJ-CITRUS-A01 | A区柑橘园环境站 | A | A区·柑橘示范园 | env |
| FJ-CITRUS-A02 | A区柑橘园墒情站 | A | A区·柑橘示范园 | soil |
| FJ-CITRUS-B01 | B区柑橘园环境站 | B | B区·柑橘试验园 | env |
| FJ-CITRUS-B02 | B区柑橘园墒情站 | B | B区·柑橘试验园 | soil |

## 五、REST 接口清单

统一前缀 `/api`；错误一律 FastAPI 标准 `{"detail": "..."}`。逐字段响应体见 [API.md](API.md) 与契约第 5 节。

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
| GET | /api/meta | 地块分组 + 阈值 + 轮询间隔 |

## 六、环境变量

全部 21 个可调参数见仓库根 `.env.example`（含中文注释与默认值），代码只从环境变量读取，零硬编码：

- 应用与数据：`APP_PORT`、`APP_VERSION`、`DB_PATH`、`DATA_DIR`
- MQTT 与设备：`MQTT_HOST`、`MQTT_PORT`、`MQTT_TOPIC`、`DEVICE_OFFLINE_SECONDS`
- 数据保留与查询上限：`TELEMETRY_RETENTION_DAYS`、`HISTORY_HOURS_MAX`、`CORS_ORIGINS`
- 大模型：`OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`、`OPENAI_TIMEOUT_SECONDS`、`OPENAI_MAX_RETRIES`、`AI_HISTORY_LIMIT`
- 模拟器与告警：`SIM_INTERVAL_SECONDS`、`SIM_DEVICES`、`SIM_BAD_PROBABILITY`、`ALERT_COOLDOWN_SECONDS`
