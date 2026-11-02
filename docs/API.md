# 接口文档 —— 智慧农业 AIoT 平台

> V1 的 11 个接口按 `docs/CONTRACT.md` 第 5 节整理，响应体逐字段冻结，前端按此消费。
> V2.0 新增的 12 条按 `docs/V2_PLAN.md` 第 6 节整理，**响应体逐字段核对过 `backend/app/schemas.py` 与
> `backend/app/routers/*.py` 源码**（以源码为准）。
> 契约是唯一真相；本文件与契约或源码冲突时以它们为准。

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
| GET | [/api/meta](#get-apimeta) | 地块 / 阈值 / 模拟器元数据（V2 已扩展） |

**V2.0 新增（12 条）**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | [/api/config](#get-apiconfig) | 当前生效的大模型配置（Key 只回显掩码） |
| PUT | [/api/config](#put-apiconfig) | 写入配置并热生效 |
| POST | [/api/config/test](#post-apiconfigtest) | 用当前配置探活并列出模型 |
| GET | [/api/models](#get-apimodels) | 运行时模型列表（V2 路径） |
| POST | [/api/reasoning/simulate](#post-apireasoningsimulate) | Context Engineering 推演（返回推演树） |
| GET | [/api/reasoning/history](#get-apireasoninghistory) | 推演历史摘要列表 |
| GET | [/api/reasoning/{id}](#get-apireasoningid) | 单次推演详情（白盒：含 prompt） |
| POST | [/api/command/execute](#post-apicommandexecute) | 下发控制指令（MQTT + 落库） |
| GET | [/api/command/history](#get-apicommandhistory) | 指令历史与回执状态 |
| GET | [/api/weather/latest](#get-apiweatherlatest) | 最新气象 + 未来 24h 预报 |
| GET | [/api/shop/skus](#get-apishopskus) | 农资 SKU 列表 |
| GET | [/api/meta](#get-apimeta) | **扩展**：2.5D 网格坐标、作物、气象段 |

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
| `db` | object | 数据库状态对象，含 `ok` / `path` |
| `db.ok` | bool | SQLite 是否可读写 |
| `db.path` | string | 来自环境变量 `DB_PATH` |
| `mqtt` | object | MQTT 状态对象，含 `connected` / `host` / `port` / `topic` |
| `mqtt.connected` | bool | 是否已连上 broker |
| `mqtt.host` / `mqtt.port` / `mqtt.topic` | — | 来自 `MQTT_HOST` / `MQTT_PORT` / `MQTT_TOPIC` |
| `llm` | object | 大模型状态对象，含 `configured` / `base_url` / `degraded` |
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
| `items[]` | object[] | 可选模型列表，每项 `{id, label, source}` |
| `items[].id` | string | 模型 id，可直接用于 `POST /api/ai/chat` 的 `model` |
| `items[].label` | string | 展示名（自动发现时等于 id） |
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
  -H 'Content-Type: application/json' \
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
    {
      "plot_code": "A",
      "plot_name": "A区·柑橘示范园",
      "devices": [
        "FJ-CITRUS-A01",
        "FJ-CITRUS-A02"
      ],
      "name": "A区柑橘园",
      "crop": "柑橘(沃柑)",
      "area_mu": 12.5,
      "stage": "果实膨大期",
      "col": 0,
      "row": 0
    },
    {
      "plot_code": "B",
      "plot_name": "B区·柑橘试验园",
      "devices": [
        "FJ-CITRUS-B01",
        "FJ-CITRUS-B02"
      ],
      "name": "B区柑橘园",
      "crop": "柑橘(沙糖桔)",
      "area_mu": 9.8,
      "stage": "果实膨大期",
      "col": 1,
      "row": 0
    }
  ],
  "thresholds": {
    "temperature": {
      "min": 15,
      "max": 35,
      "critical_min": 5,
      "critical_max": 38
    },
    "humidity": {
      "min": 40,
      "max": 85,
      "critical_min": 30,
      "critical_max": 95
    },
    "soil_moisture": {
      "min": 35,
      "max": 80,
      "critical_min": 25
    }
  },
  "sim_interval_seconds": 5,
  "crops": [
    {
      "crop_code": "citrus-wo",
      "name": "柑橘(沃柑)",
      "stage": "果实膨大期",
      "plot_codes": [
        "A"
      ],
      "area_mu": 12.5
    },
    {
      "crop_code": "citrus-st",
      "name": "柑橘(沙糖桔)",
      "stage": "果实膨大期",
      "plot_codes": [
        "B"
      ],
      "area_mu": 9.8
    }
  ],
  "weather": {
    "interval_seconds": 30,
    "topic": "agri/weather/+",
    "items": [
      {
        "ts": "2026-11-02T11:42:11+08:00",
        "temperature": 26.4,
        "humidity": 68.2,
        "rainfall_mm": 0.0,
        "wind_dir": "东南",
        "wind_level": 2,
        "condition": "晴"
      },
      {
        "ts": "2026-11-02T11:42:11+08:00",
        "temperature": 27.1,
        "humidity": 61.5,
        "rainfall_mm": 0.0,
        "wind_dir": "东南",
        "wind_level": 2,
        "condition": "晴"
      }
    ]
  }
}
```

**阈值语义**（同时是后端告警判定规则）

| 指标 | 正常区间 | 告警 |
|---|---|---|
| temperature | 15 ~ 35 ℃ | >38 或 <5 → `critical`；35~38 或 5~15 → `warning` |
| humidity | 40 ~ 85 % | >95 或 <30 → `critical`；>85 或 <40 → `warning` |
| soil_moisture | 35 ~ 80 % | <35 → `warning`；<25 → `critical` |

`sim_interval_seconds` 来自 `SIM_INTERVAL_SECONDS`，与前端 5000ms 轮询保持一致观感。

**V2.0 扩展字段**（V1 三个字段逐字不变，只在末尾追加）

| 字段 | 类型 | 说明 |
|---|---|---|
| `plots` | object[] | 地块列表，每项字段见下表 |
| `thresholds` | object | 告警阈值，含 `temperature` / `humidity` / `soil_moisture` 三项（见上表） |
| `sim_interval_seconds` | int | 遥测上报间隔，来自 `SIM_INTERVAL_SECONDS` |
| `crops` | object[] | **V2 新增**：作物清单，每项 `{crop_code, name, stage, plot_codes, area_mu}` |
| `weather` | object | **V2 新增**：气象元信息 `{interval_seconds, topic, items[]}`；`items[]` 是各试验地块的最新观测，无数据时为空数组 |

**`plots[]` 单地块字段**

| 字段 | 类型 | 说明 |
|---|---|---|
| `plot_code` | string | 地块代码（V1） |
| `plot_name` | string | 地块全名（V1） |
| `devices` | string[] | 该地块设备清单（V1） |
| `name` | string \| null | **V2** 简称，如 `A区柑橘园` |
| `crop` | string \| null | **V2** 作物 |
| `area_mu` | number \| null | **V2** 面积（亩） |
| `stage` | string \| null | **V2** 物候期 |
| `col` / `row` | int \| null | **V2** 2.5D 网格坐标 |

**`weather` 段字段**

| 字段 | 类型 | 说明 |
|---|---|---|
| `interval_seconds` | int | 气象上报间隔，来自 `WEATHER_INTERVAL_SECONDS` |
| `topic` | string | 气象 MQTT 主题，固定 `agri/weather/+` |
| `items[]` | object[] | 各地块最新气象观测，结构与 `GET /api/weather/latest` 的 `latest` 相同 |

---

## GET /api/config

当前**生效**的大模型配置。`api_key` 完整值永不返回，只回显掩码。

**请求**

```bash
curl -s http://127.0.0.1:8000/api/config
```

**响应 200（还没配过任何 Key）**

```json
{
  "base_url": null,
  "api_key_masked": null,
  "model": null,
  "configured": false,
  "source": "mock",
  "path": "/data/runtime_config.json"
}
```

**响应 200（在大屏齿轮弹窗里填过 base_url / Key / 模型之后）**

```json
{
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "api_key_masked": "sk-****abcd",
  "model": "qwen-plus",
  "configured": true,
  "source": "runtime",
  "path": "/data/runtime_config.json"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `base_url` | string \| null | 生效的 OpenAI 兼容地址 |
| `api_key_masked` | string \| null | **掩码**，形如 `sk-****abcd`；Key 长度 ≤ 8 时只回 `"****"`；无 Key 为 `null` |
| `model` | string \| null | 生效模型名 |
| `configured` | bool | `base_url` 与 `api_key` **同时**有值才为 `true` |
| `source` | string | `"runtime"`（来自配置文件）\| `"env"`（来自环境变量）\| `"mock"`（都没配） |
| `path` | string | 配置文件绝对路径，来自 `RUNTIME_CONFIG_PATH` |

**配置优先级**：`runtime_config.json` > 环境变量（`OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL`）> 内置 Mock。
即**用户在 WebUI 里填的配置覆盖服务器环境变量，改完立即生效，不需要重启容器**。

---

## PUT /api/config

写 `RUNTIME_CONFIG_PATH` 并**立即热生效**（每次调用都重新读文件，进程内无缓存）。

**请求**

```bash
curl -s -X PUT http://127.0.0.1:8000/api/config \
  -H 'Content-Type: application/json' \
  -d '{"base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1","api_key":"sk-你的Key","model":"qwen-plus"}'
```

**请求体**（三个字段全部可选）

| 字段 | 类型 | 说明 |
|---|---|---|
| `base_url` | string \| null | 传空串或 `null` = 清除该项 |
| `api_key` | string \| null | **语义特殊，见下表** |
| `model` | string \| null | 传空串或 `null` = 清除该项 |

**`api_key` 的三种语义**（实测行为）

| 传什么 | 效果 |
|---|---|
| 键**缺省**（body 里没有 `api_key`） | 保持不变 |
| `""`（空串） | 保持不变（方便前端提交表单时不误清 Key） |
| `null` | **清除**已保存的 Key |
| 非空字符串 | 覆盖为新值 |

**响应 200**：与 `GET /api/config` 完全同结构，返回写盘后的最新值（仍只有掩码）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `base_url` | string \| null | 写盘后的生效地址 |
| `api_key_masked` | string \| null | 写盘后的 Key 掩码（**永不返回明文**） |
| `model` | string \| null | 写盘后的生效模型 |
| `configured` | bool | `base_url` 与 `api_key` 是否同时有值 |
| `source` | string | 写盘后必然为 `"runtime"`（文件已存在且被优先读取） |
| `path` | string | 配置文件绝对路径 |

> 实测：传 `"sk-demo1234567890abcd"` → 回显 `"sk-****abcd"`；随后传 `api_key: ""` 掩码不变（仍 `sk-****abcd`）；再传 `api_key: null` → 掩码变 `null` 且 `configured` 回落 `false`。
> 落盘用「先写 `.json.tmp` 再 `replace`」的原子写，不会写出半截文件。

---

## POST /api/config/test

用**当前生效配置**探活 `GET {base_url}/models`。**失败也返回 200**（`ok=false`），绝不 5xx。

**请求**（无请求体）

```bash
curl -s -X POST http://127.0.0.1:8000/api/config/test
```

**响应 200 — 三种实测情况**

未配置 `base_url`：

```json
{ "ok": false, "latency_ms": 0, "models": [], "error": "base_url 未配置" }
```

`base_url` 可达但 Key 无效：

```json
{
  "ok": false,
  "latency_ms": 345,
  "models": [],
  "error": "HTTPStatusError: Client error '401 Unauthorized' for url 'https://dashscope.aliyuncs.com/compatible-mode/v1/models'"
}
```

探活成功：

```json
{ "ok": true, "latency_ms": 231, "models": ["qwen-plus", "qwen-turbo"], "error": null }
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `ok` | bool | 是否探活成功 |
| `latency_ms` | int | 本次探活耗时毫秒 |
| `models` | string[] | 从响应 `data[].id` 抽取的模型 id 列表；失败为空数组 |
| `error` | string \| null | 失败原因（`类型名: 消息`），成功为 `null` |

> 探活超时用的是 `OPENAI_TIMEOUT_SECONDS`（默认 20s），**不是** `REASONING_TIMEOUT_SECONDS`。

---

## GET /api/models

V2 新增路径，返回运行时可用模型列表；与 V1 的 `GET /api/ai/models` **同源同结构**（V1 路径保留为别名，两者响应完全一致）。

**请求**

```bash
curl -s http://127.0.0.1:8000/api/models
```

**响应 200（无 Key，走内置 Mock 列表）**

```json
{
  "configured": false,
  "degraded": true,
  "default_model": "mock-agronomist",
  "error": "OPENAI_BASE_URL 未配置，已回落 Mock 模型列表",
  "items": [
    { "id": "mock-agronomist", "label": "Mock 农技专家（离线演示）", "source": "mock" },
    { "id": "mock-citrus-expert", "label": "Mock 柑橘栽培专家", "source": "mock" },
    { "id": "mock-irrigation", "label": "Mock 水肥一体化顾问", "source": "mock" }
  ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `configured` | bool | 是否配好了 base_url + api_key |
| `degraded` | bool | `true` = 当前走 Mock 列表 |
| `default_model` | string | 默认模型 id；未配置时 `mock-agronomist` |
| `error` | string \| null | 降级原因 |
| `items[]` | object[] | 可选模型列表，每项 `{id, label, source}` |
| `items[].id` | string | 模型 id，可直接用于 `POST /api/ai/chat` 的 `model` |
| `items[].label` | string | 展示名 |
| `items[].source` | string | `"remote"`（从 `{base_url}/models` 发现）\| `"mock"` |

---

## POST /api/reasoning/simulate

Context Engineering 推演：组装地块上下文 → 调大模型 → 返回**推演树 JSON**（前端按树渲染）。
无 Key / 超时 / 非 JSON / Schema 校验失败一律降级为本地农学先验规则引擎，**HTTP 永远 200**。

**请求**

```bash
curl -s -X POST http://127.0.0.1:8000/api/reasoning/simulate \
  -H 'Content-Type: application/json' \
  -d '{"plot_code":"A"}'
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `plot_code` | string | 是 | 地块代码（`A` / `B`），长度 1~32，不能为空白 |
| `node_id` | string \| null | 否 | 指定从哪个节点展开（不传则从根节点） |

**响应 200（无 Key 时的真实响应，已省略长文本）**

```json
{
  "reasoning_id": "rs_20261102T114657_1a2b",
  "plot_code": "A",
  "generated_at": "2026-11-02T11:46:57+08:00",
  "source": "fallback",
  "model": "local-agronomy-rules",
  "latency_ms": 1,
  "degraded": true,
  "error": "大模型未配置（无 base_url 或 api_key），已降级为本地农学先验规则引擎",
  "corrected": false,
  "context": {
    "plot": {
      "plot_code": "A", "plot_name": "A区·柑橘示范园", "name": "A区柑橘园",
      "crop": "柑橘(沃柑)", "area_mu": 12.5, "stage": "果实膨大期", "col": 0, "row": 0
    },
    "metrics": {
      "temperature": null, "humidity": null, "soil_moisture": null,
      "soil_temp": null, "battery": null
    },
    "metrics_stats": {
      "temperature": { "avg": null, "min": null, "max": null, "latest": null, "count": 0 },
      "humidity": { "avg": null, "min": null, "max": null, "latest": null, "count": 0 },
      "soil_moisture": { "avg": null, "min": null, "max": null, "latest": null, "count": 0 },
      "soil_temp": { "avg": null, "min": null, "max": null, "latest": null, "count": 0 },
      "battery": { "avg": null, "min": null, "max": null, "latest": null, "count": 0 }
    },
    "weather": {
      "ts": "2026-11-02T11:42:11+08:00", "temperature": 26.4, "humidity": 68.2,
      "rainfall_mm": 0.0, "wind_dir": "东南", "wind_level": 2, "condition": "晴"
    },
    "thresholds": {
      "temperature": { "min": 15, "max": 35, "critical_min": 5, "critical_max": 38 },
      "humidity": { "min": 40, "max": 85, "critical_min": 30, "critical_max": 95 },
      "soil_moisture": { "min": 35, "max": 80, "critical_min": 25 }
    }
  },
  "tree": {
    "nodes": [
      { "id": "root", "type": "current", "level": 0, "parent": null, "label": "当前数据",
        "sub": "墒情 None% · 气温 None℃ · 湿度 None%", "severity": "good",
        "command": null, "effect": null, "sku_keywords": [] },
      { "id": "risk_1", "type": "risk", "level": 1, "parent": "root", "label": "减产风险 0%",
        "sub": "墒情 None% ≥ 正常下限 35%", "severity": "good",
        "command": null, "effect": null, "sku_keywords": [] },
      { "id": "plan_1", "type": "plan", "level": 1, "parent": "root", "label": "预防性滴灌 15 分钟",
        "sub": "维持墒情在 35~80% 区间", "severity": "good",
        "command": { "action": "irrigation_on", "params": { "duration_min": 15 },
                     "device_code": "FJ-CITRUS-A02" },
        "effect": { "soil_moisture_delta": 4.0, "yield_recover_pct": 0.0 },
        "sku_keywords": ["滴灌带"] }
    ],
    "links": [ { "source": "root", "target": "risk_1" }, { "source": "root", "target": "plan_1" } ]
  },
  "summary": "A区柑橘园 当前墒情 None%、气温 None℃，各项指标处于正常区间，暂无减产风险。",
  "yield_loss_pct": 0.0,
  "power_kwh": 1.88,
  "whitebox": [
    { "step": "环境数据读取",
      "detail": "读取 A区柑橘园 最近 10 分钟遥测，共 0 条样本（设备 FJ-CITRUS-A01, FJ-CITRUS-A02）：气温 None℃、湿度 None%、墒情 None%、土温 None℃、电量 None%；气象：晴 26.4℃ 湿度 68.2% 降水 0.0mm 东南风 2 级",
      "ts": "2026-11-02T11:46:57+08:00" },
    { "step": "匹配农学规则",
      "detail": "命中规则：亩均滴灌耗电 0.15 kWh/亩 → 地块 A区柑橘园 面积 12.5 亩 × 0.15 kWh/亩 = 1.88 kWh。…",
      "ts": "2026-11-02T11:46:57+08:00" },
    { "step": "大模型结论生成",
      "detail": "大模型不可用，已由本地农学先验规则引擎（knowledge.py）产出同结构结论：减产 0.0%、耗电 1.88 kWh，结构与数字口径与主模型路径完全一致。",
      "ts": "2026-11-02T11:46:57+08:00" }
  ],
  "prior": { "yield_loss_pct": 0.0, "power_kwh": 1.88, "level": "normal", "hours_below_min": 0.0 }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `reasoning_id` | string | 本次推演 id，形如 `rs_20261102T114657_1a2b`，可用于 `GET /api/reasoning/{id}` |
| `plot_code` | string | 回显请求的地块代码 |
| `generated_at` | string | 结论生成时间（ISO8601 带时区） |
| `source` | string | `"primary"`（大模型返回并通过 Schema 校验）\| `"fallback"`（降级到本地规则引擎） |
| `model` | string | 实际产出方：模型名，或降级时的 `"local-agronomy-rules"` |
| `latency_ms` | int | 推演耗时 |
| `degraded` | bool | 是否走了降级 |
| `error` | string \| null | 降级原因 |
| `corrected` | bool | 大模型数字与先验偏差超过 `REASONING_PRIOR_TOLERANCE_PCT`（15%）时，已用先验数字纠正 |
| `context` | object | 送入大模型的上下文：`plot` / `metrics` / `metrics_stats` / `weather`（可为 `null`）/ `thresholds` |
| `tree` | object | 推演树，含 `nodes[]` 与 `links[]` 两个字段 |
| `tree.nodes[]` | object[] | 推演树节点，见下表 |
| `tree.links[]` | object[] | `{source, target}` 节点连线 |
| `summary` | string | 一句话结论 |
| `yield_loss_pct` | number | 预计减产百分比 |
| `power_kwh` | number | 预计耗电（kWh） |
| `whitebox` | object[] | 白盒推理链，每项 `{step, detail, ts}`；**固定 3 步**：环境数据读取 / 匹配农学规则 / 大模型结论生成 |
| `prior` | object \| null | 本地先验模型的独立测算：`{yield_loss_pct, power_kwh, level, hours_below_min}` |

**`tree.nodes[]` 单节点字段**

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 节点 id（`root` / `risk_N` / `plan_N`） |
| `type` | string | `"current"` \| `"risk"` \| `"plan"` |
| `level` | int | 层级，根为 0 |
| `parent` | string \| null | 父节点 id |
| `label` / `sub` | string | 主标题 / 副标题 |
| `severity` | string | `"good"` \| `"warn"` \| `"high"` |
| `command` | object \| null | 该节点可下发的指令 `{action, params, device_code}`；无则 `null` |
| `effect` | object \| null | 预期效果 `{soil_moisture_delta, yield_recover_pct}`；无则 `null` |
| `sku_keywords` | string[] | 关联农资关键词，可用于 `GET /api/shop/skus?keyword=` |

**错误码**

| 状态码 | 场景 | 响应体 |
|---|---|---|
| 422 | `plot_code` 缺失或为空白 | FastAPI 标准校验错误 |
| 200 | 大模型不可用 / 超时 / 返回非 JSON | 降级结果，`source="fallback"` |

> 推演超时用 `REASONING_TIMEOUT_SECONDS`（默认 45s，比问答的 20s 宽）。

---

## GET /api/reasoning/history

推演历史**摘要**列表（**不含完整 prompt**，减体积）。

**请求**

```bash
curl -s 'http://127.0.0.1:8000/api/reasoning/history?limit=20'
```

| 查询参数 | 默认 | 约束 |
|---|---|---|
| `limit` | 20 | 必须 > 0，服务端上限 `REASONING_HISTORY_LIMIT`（100） |

**响应 200**

```json
{
  "total": 2,
  "items": [
    {
      "reasoning_id": "rs_20261102T114346_3cca",
      "plot_code": "A",
      "source": "fallback",
      "model": "local-agronomy-rules",
      "latency_ms": 1,
      "degraded": true,
      "error": "大模型未配置（无 base_url 或 api_key），已降级为本地农学先验规则引擎",
      "created_at": "2026-11-02T11:43:46+08:00",
      "summary": "A区柑橘园 当前墒情 None%、气温 None℃，各项指标处于正常区间，暂无减产风险。",
      "yield_loss_pct": 0.0
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `total` | int | 返回条数 |
| `items[]` | object[] | 推演摘要列表，字段见下表 |
| `items[].reasoning_id` | string | 推演 id |
| `items[].plot_code` | string | 地块代码 |
| `items[].source` | string | `"primary"` \| `"fallback"` |
| `items[].model` | string | 实际产出方 |
| `items[].latency_ms` | int | 耗时毫秒 |
| `items[].degraded` | bool | 注意与 `GET /api/ai/history` 的 `degraded`（int）**类型不同** |
| `items[].error` | string \| null | 降级原因 |
| `items[].summary` | string \| null | 一句话结论 |
| `items[].yield_loss_pct` | number \| null | 预计减产百分比 |
| `items[].created_at` | string | 落库时间（ISO8601 带时区） |

---

## GET /api/reasoning/{id}

单次推演**白盒详情**：结构 = `POST /api/reasoning/simulate` 的响应 **+ `prompt` + `raw_response`**。

**请求**

```bash
curl -s http://127.0.0.1:8000/api/reasoning/rs_20261102T114346_3cca
```

**响应 200**：字段 = `simulate` 的全部 16 个字段 **+ 下面 2 个**

| 字段 | 类型 | 说明 |
|---|---|---|
| `reasoning_id` | string | 推演 id |
| `plot_code` | string | 地块代码 |
| `generated_at` | string | 生成时间 |
| `source` | string | `"primary"` \| `"fallback"` |
| `model` | string | 实际产出方 |
| `latency_ms` | int | 耗时毫秒 |
| `degraded` | bool | 是否降级 |
| `error` | string \| null | 降级原因 |
| `corrected` | bool | 是否用先验数字纠正过大模型输出 |
| `context` | object | 送入大模型的上下文 |
| `tree` | object | 推演树 `{nodes[], links[]}` |
| `summary` | string | 一句话结论 |
| `yield_loss_pct` | number | 预计减产百分比 |
| `power_kwh` | number | 预计耗电 kWh |
| `whitebox` | object[] | 白盒推理链 |
| `prior` | object \| null | 本地先验测算 |
| `prompt` | string \| null | 实际发给大模型的**完整 prompt 原文**（System + User，实测约 2.2K 字符（UTF-8 约 3.0 KB，随上下文略有浮动）） |
| `raw_response` | string \| null | 大模型原始返回文本；降级路径下为 `null` |

**响应 404**

```json
{ "detail": "reasoning not found" }
```

> 路由注册顺序：`/history` **必须**在 `/{reasoning_id}` 之前，否则 `history` 会被当成一个 id。

---

## POST /api/command/execute

下发控制指令：落库 `status=dispatched` + 向 `agri/command/{plot_code}/{device_code}` 发 QoS 1 消息，**立即返回**，不等回执。

**请求**

```bash
curl -s -X POST http://127.0.0.1:8000/api/command/execute \
  -H 'Content-Type: application/json' \
  -d '{"reasoning_id":"rs_20261102T114346_3cca","plot_code":"A","device_code":"FJ-CITRUS-A01","node_id":"plan_1","action":"irrigation_on","params":{"duration_min":40}}'
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `reasoning_id` | string \| null | 否 | 关联的推演 id |
| `plot_code` | string | 是 | 地块代码，长度 1~32 |
| `device_code` | string | 是 | 目标设备，长度 1~64 |
| `node_id` | string \| null | 否 | 关联的推演树节点 |
| `action` | string | 是 | **白名单**：`irrigation_on` \| `irrigation_off` \| `pesticide_dose` \| `ventilation_on` |
| `params` | object | 否 | 透传给设备的参数，如 `{"duration_min":40}` |

**响应 200（实测）**

```json
{
  "command_id": "cmd_20261102T114346_d629",
  "topic": "agri/command/A/FJ-CITRUS-A01",
  "payload": {
    "command_id": "cmd_20261102T114346_d629",
    "action": "irrigation_on",
    "params": { "duration_min": 40 },
    "issued_at": "2026-11-02T11:43:46+08:00"
  },
  "status": "dispatched"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `command_id` | string | 形如 `cmd_20261102T114346_d629` |
| `topic` | string | 实际发布的 MQTT 主题 |
| `payload` | object | 实际发布的 JSON（与上表字段一致） |
| `status` | string | 下发后固定为 `"dispatched"` |

**错误码**

| 状态码 | 场景 |
|---|---|
| 422 | `action` 不在白名单 / 缺 `plot_code` 或 `device_code` |

> **MQTT 不可达也不报错**：消息发不出去时仍返回 200 + `status="dispatched"`，该指令会在超时清扫时被标为 `timeout`。

---

## GET /api/command/history

指令历史与回执状态流转。

**请求**

```bash
curl -s 'http://127.0.0.1:8000/api/command/history?limit=20'
```

| 查询参数 | 默认 | 约束 |
|---|---|---|
| `limit` | 20 | 必须 > 0，服务端上限 `COMMAND_HISTORY_LIMIT`（100） |

**响应 200（实测）**

```json
{
  "total": 2,
  "items": [
    {
      "command_id": "cmd_20261102T114346_d629",
      "reasoning_id": null,
      "plot_code": "A",
      "device_code": "FJ-CITRUS-A01",
      "node_id": null,
      "action": "irrigation_on",
      "params": { "duration_min": 40 },
      "topic": "agri/command/A/FJ-CITRUS-A01",
      "payload": {
        "command_id": "cmd_20261102T114346_d629",
        "action": "irrigation_on",
        "params": { "duration_min": 40 },
        "issued_at": "2026-11-02T11:43:46+08:00"
      },
      "status": "dispatched",
      "ack_at": null,
      "created_at": "2026-11-02T11:43:46+08:00",
      "detail": "已下发，等待模拟器回执"
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `total` | int | 返回条数 |
| `items[]` | object[] | 指令列表，字段见下表 |
| `items[].command_id` | string | 指令 id |
| `items[].reasoning_id` | string \| null | 关联的推演 id |
| `items[].plot_code` | string | 地块代码 |
| `items[].device_code` | string | 目标设备 |
| `items[].node_id` | string \| null | 关联的推演树节点 |
| `items[].action` | string | 动作（白名单内） |
| `items[].params` | object \| null | 下发参数 |
| `items[].topic` | string | MQTT 主题 |
| `items[].payload` | object \| null | 实际发布的报文 |
| `items[].status` | string | `dispatched`（已下发）\| `executed`（模拟器回执成功）\| `failed`（回执失败）\| `timeout`（超时未回执） |
| `items[].ack_at` | string \| null | 收到回执的时间；未回执为 `null` |
| `items[].created_at` | string | 下发时间 |
| `items[].detail` | string \| null | 状态的中文说明 |


**`timeout` 的产生**：后台定时把超过 `COMMAND_ACK_TIMEOUT_SECONDS`（默认 30s）仍无回执的 `dispatched` 指令改为 `timeout`，
`detail` 文案为 `"超过 30s 未收到回执，已标记 timeout"`。
回执由模拟器发布到 `agri/command_ack/{plot_code}/{device_code}`（QoS 1）。

---

## GET /api/weather/latest

最新气象观测 + 未来 24h 模拟预报。**永远 200**，无数据时 `latest=null`。

**请求**

```bash
curl -s 'http://127.0.0.1:8000/api/weather/latest?plot_code=A'
```

| 查询参数 | 默认 | 说明 |
|---|---|---|
| `plot_code` | `"A"` | 地块代码 |

**响应 200 — 有观测数据（实测，`forecast` 实际返回 24 条，此处只列前 3 条）**

```json
{
  "plot_code": "A",
  "latest": {
    "ts": "2026-11-02T11:42:11+08:00",
    "temperature": 26.4,
    "humidity": 68.2,
    "rainfall_mm": 0.0,
    "wind_dir": "东南",
    "wind_level": 2,
    "condition": "晴"
  },
  "forecast": [
    {
      "ts": "2026-11-02T12:00:00+08:00",
      "temperature": 29.9,
      "humidity": 55.5,
      "rainfall_mm": 0.0,
      "wind_dir": "南",
      "wind_level": 2,
      "condition": "晴"
    },
    {
      "ts": "2026-11-02T13:00:00+08:00",
      "temperature": 30.7,
      "humidity": 52.6,
      "rainfall_mm": 0.0,
      "wind_dir": "西南",
      "wind_level": 2,
      "condition": "晴"
    },
    {
      "ts": "2026-11-02T14:00:00+08:00",
      "temperature": 31.2,
      "humidity": 50.8,
      "rainfall_mm": 0.0,
      "wind_dir": "西",
      "wind_level": 1,
      "condition": "晴"
    }
  ],
  "count": 1,
  "interval_seconds": 30,
  "source": "observed"
}
```

**响应 200 — 还没有任何气象上报（实测）**

```json
{ "plot_code": "A", "latest": null, "forecast": [], "count": 0, "interval_seconds": 30, "source": "none" }
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `latest` | object \| null | 最新一条观测，无数据为 `null` |
| `forecast` | object[] | 未来 `WEATHER_FORECAST_HOURS`（24）小时的逐时预报；无观测时为空数组 |
| `count` | int | 该地块累计气象条数 |
| `interval_seconds` | int | 来自 `WEATHER_INTERVAL_SECONDS` |
| `source` | string | `"observed"`（真实观测）\| `"mock"` \| `"none"`（无数据） |

**气象点（`latest` 与 `forecast[]` 同结构）**

| 字段 | 类型 | 说明 |
|---|---|---|
| `ts` | string | ISO8601 带时区 |
| `temperature` / `humidity` | number \| null | 气温 ℃ / 相对湿度 % |
| `rainfall_mm` | number \| null | 降水量 mm |
| `wind_dir` | string \| null | 风向中文（北 / 东北 / … / 西北） |
| `wind_level` | int \| null | 风力等级 |
| `condition` | string \| null | 天气现象：`晴` / `阴` / `小雨` / `中雨` |

> 预报无第三方数据源，是**以最新观测为锚点的确定性日变化推演**（15 时最热、3 时最冷），离线演示时也能画出 24h 曲线。

---

## GET /api/shop/skus

Mock 农资 SKU 列表（启动时幂等 seed 6 条）。

**请求**

```bash
curl -s 'http://127.0.0.1:8000/api/shop/skus?keyword=抗旱'
```

| 查询参数 | 默认 | 说明 |
|---|---|---|
| `keyword` | 无 | 模糊匹配 `keywords` / `name` / `description` / `category` |

**响应 200（实测，`keyword=抗旱`）**

```json
{
  "total": 2,
  "keyword": "抗旱",
  "items": [
    {
      "id": "sku-drip-tape",
      "name": "滴灌带",
      "category": "灌溉",
      "price": 210.0,
      "unit": "卷(1000m)",
      "image": "sku-drip-tape",
      "stock": 60,
      "description": "贴片式滴灌带，滴头间距 30cm，流量 2L/h，配合水肥一体化少量多次。",
      "keywords": "滴灌,灌溉,缺水,抗旱,墒情,水肥一体化"
    },
    {
      "id": "sku-water-retainer",
      "name": "抗旱保水剂",
      "category": "土壤调理",
      "price": 68.0,
      "unit": "袋(5kg)",
      "image": "sku-water-retainer",
      "stock": 120,
      "description": "高分子吸水树脂，按 1:200 吸水，树盘撒施可提升土壤持水能力 30% 以上。",
      "keywords": "抗旱,保水,保墒,干旱,缺水,土壤"
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `total` | int | 命中条数 |
| `keyword` | string \| null | 回显查询词；未传时为 `null` |
| `items[]` | object[] | SKU 列表，字段见下表 |
| `items[].id` | string | SKU id |
| `items[].name` | string | 名称 |
| `items[].category` | string | 分类 |
| `items[].price` | number | 单价（元） |
| `items[].unit` | string | 规格单位 |
| `items[].image` | string \| null | 图片标识（前端按 id 映射本地图，不依赖外网） |
| `items[].stock` | int | 库存 |
| `items[].description` | string \| null | 描述 |
| `items[].keywords` | string \| null | 逗号分隔的关键词，模糊匹配的主要来源 |

**内置 6 条 SKU**（`GET /api/shop/skus` 无参数时 `total=6`）

| id | name | category | price | unit |
|---|---|---|---|---|
| sku-acaricide | 杀螨剂 | 植保 | 42.0 | 瓶(500ml) |
| sku-calcium-foliar | 叶面钙肥 | 肥料 | 38.0 | 瓶(1L) |
| sku-citrus-soluble | 柑橘专用水溶肥 | 肥料 | 156.0 | 袋(20kg) |
| sku-drip-tape | 滴灌带 | 灌溉 | 210.0 | 卷(1000m) |
| sku-soil-probe | 土壤墒情探头 | 设备 | 320.0 | 支 |
| sku-water-retainer | 抗旱保水剂 | 土壤调理 | 68.0 | 袋(5kg) |

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
