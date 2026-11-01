# 接口文档 —— 智慧农业 AIoT 平台 v1.0.0

> 本文件按 `docs/CONTRACT.md` 第 5 节整理，响应体逐字段冻结，前端按此消费。
> 契约是唯一真相；本文件与契约冲突时以契约为准。

- **统一前缀**：`/api`
- **数据格式**：`application/json; charset=utf-8`
- **时间格式**：一律 ISO8601 带时区字符串，例如 `2026-01-01T12:00:00+08:00`
- **错误格式**：FastAPI 标准 `{"detail": "..."}`
- **交互式文档**：服务起来后访问 `http://<host>:8000/docs`（Swagger UI）

---

## 目录

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | [/api/health](#get-apihealth) | 健康检查（含 DB / MQTT / 大模型状态） |
| GET | [/api/devices](#get-apidevices) | 设备列表（含最新遥测与在线状态） |
| GET | [/api/telemetry/latest](#get-apitelemetrylatest) | 全部设备最新遥测 |
| GET | [/api/telemetry/history](#get-apitelemetryhistory) | 单设备历史曲线 |
| GET | [/api/telemetry/summary](#get-apitelemetrysummary) | 全局统计聚合 |
| GET | [/api/alerts](#get-apialerts) | 告警列表 |
| POST | [/api/alerts/{id}/ack](#post-apialertsidack) | 确认告警 |
| GET | [/api/ai/models](#get-apiaimodels) | 可用大模型列表 |
| POST | [/api/ai/chat](#post-apiaichat) | 农技问答 |
| GET | [/api/ai/history](#get-apiaihistory) | 问答历史 |
| GET | [/api/meta](#get-apimeta) | 地块 / 阈值 / 模拟器元数据 |

---

## GET /api/health

健康检查。**容器健康检查也用它**，是部署后第一个该验证的接口。

**请求**

```bash
curl -s http://127.0.0.1:8000/api/health
```

**响应 200**

```json
{
  "status": "ok",
  "version": "1.0.0",
  "uptime_s": 12.3,
  "db": { "ok": true, "path": "/data/agri.db" },
  "mqtt": { "connected": true, "host": "mosquitto", "port": 1883, "topic": "agri/telemetry/+/+" },
  "llm": { "configured": false, "base_url": null, "degraded": true }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | string | 固定 `"ok"`（进程活着） |
| `version` | string | 来自环境变量 `APP_VERSION` |
| `uptime_s` | number | 进程运行秒数 |
| `db.ok` | bool | SQLite 是否可读写 |
| `db.path` | string | 来自环境变量 `DB_PATH` |
| `mqtt.connected` | bool | 是否已连上 broker |
| `mqtt.host` / `mqtt.port` / `mqtt.topic` | — | 来自 `MQTT_HOST` / `MQTT_PORT` / `MQTT_TOPIC` |
| `llm.configured` | bool | 是否配了 `OPENAI_API_KEY` |
| `llm.base_url` | string \| null | 来自 `OPENAI_BASE_URL`，未配置为 `null` |
| `llm.degraded` | bool | `true` = AI 接口会返回 Mock 答案 |

> `mqtt.connected=false` 时服务仍返回 200，大屏其余部分照常工作，只是不再有新数据入库。

---

## GET /api/devices

设备列表，含每台设备的最新一条遥测与在线状态。

**请求**

```bash
curl -s http://127.0.0.1:8000/api/devices
```

**响应 200**

```json
{
  "total": 4,
  "online": 3,
  "offline": 1,
  "items": [
    {
      "device_code": "FJ-CITRUS-A01",
      "name": "A区柑橘园环境站",
      "plot_code": "A",
      "plot_name": "A区·柑橘示范园",
      "type": "env",
      "location": "福建省南平市·A区",
      "status": "online",
      "last_seen": "2026-01-01T12:00:00+08:00",
      "latest": {
        "ts": "2026-01-01T12:00:00+08:00",
        "temperature": 26.4,
        "humidity": 68.2,
        "soil_moisture": 52.1,
        "soil_temp": 22.7,
        "battery": 93.5
      }
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `total` / `online` / `offline` | int | 设备总数 / 在线数 / 离线数 |
| `items[].type` | string | `env`（环境站）或 `soil`（墒情站） |
| `items[].status` | string | `online` \| `offline` |
| `items[].last_seen` | string \| null | 最后一次上报时间 |
| `items[].latest` | object \| null | 最新遥测；从未上报过则为 `null` |

**在线判定**：`last_seen` 距当前时间 > `DEVICE_OFFLINE_SECONDS`（默认 30 秒）即判为 `offline`。

**设备清单**（模拟器与种子数据一致）

| device_code | name | plot_code | plot_name | type |
|---|---|---|---|---|
| FJ-CITRUS-A01 | A区柑橘园环境站 | A | A区·柑橘示范园 | env |
| FJ-CITRUS-A02 | A区柑橘园墒情站 | A | A区·柑橘示范园 | soil |
| FJ-CITRUS-B01 | B区柑橘园环境站 | B | B区·柑橘试验园 | env |
| FJ-CITRUS-B02 | B区柑橘园墒情站 | B | B区·柑橘试验园 | soil |

---

## GET /api/telemetry/latest

所有设备的最新遥测，扁平化数组，适合大屏顶部指标条。

**请求**

```bash
curl -s http://127.0.0.1:8000/api/telemetry/latest
```

**响应 200**

```json
{
  "items": [
    {
      "device_code": "FJ-CITRUS-A01",
      "plot_code": "A",
      "ts": "2026-01-01T12:00:00+08:00",
      "temperature": 26.4,
      "humidity": 68.2,
      "soil_moisture": 52.1,
      "soil_temp": 22.7,
      "battery": 93.5
    }
  ]
}
```

元素即 `/api/devices` 的 `latest` 对象，额外带 `device_code` 与 `plot_code`。

---

## GET /api/telemetry/history

单台设备的历史曲线数据，供 RealtimeChart 使用。

**查询参数**

| 参数 | 类型 | 必填 | 默认 | 上限 | 说明 |
|---|---|---|---|---|---|
| `device_code` | string | **是** | — | — | 设备编号 |
| `hours` | int | 否 | 1 | `HISTORY_HOURS_MAX`（168） | 回溯小时数 |
| `limit` | int | 否 | 720 | 5000 | 最多返回点数 |

**请求**

```bash
curl -s "http://127.0.0.1:8000/api/telemetry/history?device_code=FJ-CITRUS-A01&hours=1&limit=720"
```

**响应 200**

```json
{
  "device_code": "FJ-CITRUS-A01",
  "hours": 1,
  "count": 120,
  "points": [
    {
      "ts": "2026-01-01T11:59:00+08:00",
      "temperature": 26.4,
      "humidity": 68.2,
      "soil_moisture": 52.1,
      "soil_temp": 22.7
    }
  ]
}
```

**要点**

- `points` 按 `ts` **升序**（曲线从左到右即时间先后）。
- 缺 `device_code` → 422（FastAPI 参数校验失败）。
- 无数据时 `points` 为 `[]`、`count` 为 `0`，仍返回 200。

---

## GET /api/telemetry/summary

全局统计聚合（平均值 / 极值），供大屏数字卡片使用。

**查询参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `hours` | int | 否 | 24 | 统计窗口小时数 |

**请求**

```bash
curl -s "http://127.0.0.1:8000/api/telemetry/summary?hours=24"
```

**响应 200**

```json
{
  "hours": 24,
  "samples": 1440,
  "temperature": { "avg": 25.1, "min": 18.2, "max": 33.9 },
  "humidity": { "avg": 66.0, "min": 41.0, "max": 88.0 },
  "soil_moisture": { "avg": 51.2, "min": 28.4, "max": 72.1 }
}
```

**要点**：窗口内无数据时，`temperature` / `humidity` / `soil_moisture` 各自的 `avg`、`min`、`max` 均为 `null`（不是 0）。

---

## GET /api/alerts

告警列表，按创建时间倒序。

**查询参数**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `limit` | int | 否 | 50 | 返回条数 |
| `only_unacked` | bool | 否 | false | 只看未确认告警 |

**请求**

```bash
curl -s "http://127.0.0.1:8000/api/alerts?limit=50&only_unacked=false"
```

**响应 200**

```json
{
  "total": 12,
  "unacked": 3,
  "items": [
    {
      "id": 1,
      "device_code": "FJ-CITRUS-A02",
      "metric": "soil_moisture",
      "value": 28.4,
      "threshold": 35.0,
      "level": "warning",
      "message": "A区柑橘园墒情站 土壤墒情 28.4% 低于下限 35%",
      "acked": 0,
      "created_at": "2026-01-01T12:00:00+08:00"
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `metric` | string | `temperature` \| `humidity` \| `soil_moisture` |
| `level` | string | `warning` \| `critical` |
| `value` / `threshold` | number | 实测值 / 被触发的阈值 |
| `acked` | int | `0` 未确认，`1` 已确认 |
| `total` / `unacked` | int | 总数 / 未确认数 |

---

## POST /api/alerts/{id}/ack

确认一条告警。

**请求**

```bash
curl -s -X POST http://127.0.0.1:8000/api/alerts/1/ack
```

**响应 200**

```json
{ "ok": true, "id": 1 }
```

**响应 404**（告警不存在）

```json
{ "detail": "alert not found" }
```

---

## GET /api/ai/models

可用大模型列表。有 Key 时自动发现，发现失败回落 Mock 列表。

**请求**

```bash
curl -s http://127.0.0.1:8000/api/ai/models
```

**响应 200（未配置 Key / 自动发现失败）**

```json
{
  "configured": false,
  "degraded": true,
  "default_model": "mock-agronomist",
  "error": null,
  "items": [
    { "id": "mock-agronomist", "label": "Mock 农技专家（离线演示）", "source": "mock" }
  ]
}
```

**响应 200（已配置 Key 且发现成功）**

```json
{
  "configured": true,
  "degraded": false,
  "default_model": "qwen-plus",
  "error": null,
  "items": [
    { "id": "qwen-plus", "label": "qwen-plus", "source": "remote" }
  ]
}
```

| 字段 | 说明 |
|---|---|
| `configured` | 是否配置了 `OPENAI_API_KEY` |
| `degraded` | `true` = 后续 chat 会走 Mock |
| `default_model` | 来自 `OPENAI_MODEL`；为空时取发现列表第一个，无 Key 时为 `mock-agronomist` |
| `error` | 发现失败原因（成功时为 `null`） |
| `items[].source` | `remote`（来自 `GET {OPENAI_BASE_URL}/models`）或 `mock` |

---

## POST /api/ai/chat

农技问答。**任何异常都降级为 Mock 答案，HTTP 仍为 200**，保证大屏永不卡死。

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `question` | string | **是** | 问题文本；为空 → 422 |
| `session_id` | string | 否 | 会话标识，用于前端历史侧栏分组 |
| `model` | string | 否 | 模型 id；省略则用 `default_model` |

**请求**

```bash
curl -s -X POST http://127.0.0.1:8000/api/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"柑橘叶子黄了怎么办","session_id":"s1","model":"qwen-plus"}'
```

**响应 200（降级）**

```json
{
  "answer": "...",
  "model": "mock-agronomist",
  "degraded": true,
  "latency_ms": 12,
  "session_id": "s1",
  "created_at": "2026-01-01T12:00:00+08:00",
  "error": null
}
```

**响应 422**（question 为空）

```json
{ "detail": [ { "type": "string_too_short", "loc": ["body", "question"], "msg": "String should have at least 1 character" } ] }
```

**降级规则**

1. 真实调用超过 `OPENAI_TIMEOUT_SECONDS`（默认 20 秒）→ 返回 Mock 答案，`degraded=true`，`error` 写明 `timeout`。
2. 调用抛任何异常（网络 / 鉴权 / 限流）→ 同上，`error` 写明原因。
3. 失败后按 `OPENAI_MAX_RETRIES`（默认 1）重试。
4. `latency_ms` 记录**端到端**耗时（含重试），是性能埋点。

---

## GET /api/ai/history

问答历史，按创建时间倒序。

**查询参数**

| 参数 | 类型 | 必填 | 默认 | 上限 | 说明 |
|---|---|---|---|---|---|
| `limit` | int | 否 | 20 | `AI_HISTORY_LIMIT`（50） | 返回条数 |

**请求**

```bash
curl -s "http://127.0.0.1:8000/api/ai/history?limit=20"
```

**响应 200**

```json
{
  "total": 37,
  "items": [
    {
      "id": 7,
      "question": "柑橘叶子黄了怎么办",
      "answer": "...",
      "model": "mock-agronomist",
      "degraded": 0,
      "latency_ms": 1200,
      "created_at": "2026-01-01T12:00:00+08:00"
    }
  ]
}
```

> 注意：这里的 `degraded` 是 **int**（`0`/`1`，直接来自 SQLite），
> 而 `/api/ai/chat` 与 `/api/health` 里的 `degraded` 是 **bool**。前端取值时按类型处理。

---

## GET /api/meta

地块、告警阈值与模拟器配置，前端启动时拉一次即可。

**请求**

```bash
curl -s http://127.0.0.1:8000/api/meta
```

**响应 200**

```json
{
  "plots": [
    { "plot_code": "A", "plot_name": "A区·柑橘示范园", "devices": ["FJ-CITRUS-A01", "FJ-CITRUS-A02"] }
  ],
  "thresholds": {
    "temperature": { "min": 15, "max": 35, "critical_min": 5, "critical_max": 38 },
    "humidity": { "min": 40, "max": 85 },
    "soil_moisture": { "min": 35, "max": 80, "critical_min": 25 }
  },
  "sim_interval_seconds": 5
}
```

**阈值语义**（同时是后端告警判定规则）

| 指标 | 正常区间 | 告警 |
|---|---|---|
| temperature | 15 ~ 35 ℃ | >38 或 <5 → `critical`；35~38 或 5~15 → `warning` |
| humidity | 40 ~ 85 % | <30 → `warning`；>95 → `warning` |
| soil_moisture | 35 ~ 80 % | <35 → `warning`；<25 → `critical` |

`sim_interval_seconds` 来自 `SIM_INTERVAL_SECONDS`，与前端 5000ms 轮询保持一致观感。

---

## 附：环境变量与接口的对应关系

| 环境变量 | 影响的接口 |
|---|---|
| `APP_PORT` | 全部（监听端口） |
| `APP_VERSION` | `GET /api/health` |
| `DB_PATH` / `DATA_DIR` | `GET /api/health`（`db.path`） |
| `MQTT_HOST` / `MQTT_PORT` / `MQTT_TOPIC` | `GET /api/health`（`mqtt.*`） |
| `DEVICE_OFFLINE_SECONDS` | `GET /api/devices`（`status`） |
| `TELEMETRY_RETENTION_DAYS` | 遥测数据保留天数（清理过期点，接口返回的数据受其约束） |
| `HISTORY_HOURS_MAX` | `GET /api/telemetry/history`（`hours` 上限） |
| `CORS_ORIGINS` | 跨域响应头 |
| `OPENAI_*` | `GET /api/ai/models`、`POST /api/ai/chat` |
| `AI_HISTORY_LIMIT` | `GET /api/ai/history`（`limit` 上限） |
| `SIM_INTERVAL_SECONDS` | `GET /api/meta` |
| `SIM_DEVICES` | 模拟器上报的设备集合 |
| `SIM_BAD_PROBABILITY` | 模拟器越界注入概率，决定 `GET /api/alerts` 里告警出现的频率 |
| `ALERT_COOLDOWN_SECONDS` | `GET /api/alerts`（同设备+指标+级别的告警冷却，防重复刷表） |
