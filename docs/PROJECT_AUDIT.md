# 项目审计报告 · 生产环境实测

> **测量时间**：2026-11-04 11:45–11:52 CST（UTC+8）
> **测量对象**：阿里云轻量应用服务器上的生产部署（三容器，公网 8000 端口）
> **测量方式**：SSH 登入目标机执行 `docker` / `curl` / `sqlite3`，以及从本机经公网直连 8000 端口。不采信任何自述数字。
> **读法**：标注 **不变量** 的项不随运行时间变化；标注 **当日快照** 的项会随时间漂移（遥测类表按 2880 条/小时线性增长）。
> 未验证项集中在第 8 节，本文不对其作任何声称。

---

## 1. 测量环境与目标机

| 项 | 实测值 | 性质 |
|---|---|---|
| 操作系统 | Ubuntu 26.04.1 LTS (resolute)，x86_64 | 不变量 |
| CPU | 2 核 | 不变量 |
| 内存 | MemTotal 1735 MB；已用 748 MB；可用 986 MB | 当日快照 |
| Swap | 4095 MB（`/swapfile`，4G），已用 97 MB；`vm.swappiness=20` | 当日快照 |
| 负载 | load average 0.06 / 0.16 / 0.13；uptime 2 天 12 小时 59 分 | 当日快照 |
| Docker | `Docker version 29.7.2, build a7dcaa6` | 不变量 |
| Docker Compose | `Docker Compose version v5.5.0` | 不变量 |
| 时区 | CST +08:00（容器与宿主一致） | 不变量 |

### 1.1 运行中的镜像（按 digest 锁定）

| 镜像 | Digest |
|---|---|
| `ghcr.io/tss-small-sunshine/agri-aiot-platform:latest` | `sha256:304c077217079e7bde9efcbe669b527fec1292d6e37338de9c19833181e7c3e7` |
| `ghcr.io/tss-small-sunshine/agri-aiot-platform-simulator:latest` | `sha256:1a13ba7da1618e4171470b9d274065de6e2dcbf6d249b93f5ec4e09138d33046` |
| `eclipse-mosquitto:2` | `sha256:860aeb5d63ce509508f6dcfb2bc8a1c1dd2bc60555b562b45ce90e52d8dabb0f` |

镜像由 GitHub Actions 构建并推送，服务器只执行 `docker compose pull && docker compose up -d`，不在本机构建。

---

## 2. 依赖清单（不变量）

| 层 | 直接依赖数 | 清单 |
|---|---|---|
| 后端 | **5** | `fastapi==0.162.0`、`uvicorn[standard]==0.54.0`、`paho-mqtt==2.1.0`、`httpx==0.28.1`、`pydantic==2.14.2` |
| 模拟器 | **1** | `paho-mqtt==2.1.0` |
| 前端（运行时） | **2** | `vue ^3.5.13`、`echarts ^5.5.1` |
| 前端（构建期） | 2 | `vite ^6.0.7`、`@vitejs/plugin-vue ^5.2.1` |

未引入：SQLAlchemy、requests、OpenAI SDK、任何 MQTT 高级封装、任何前端 UI 组件库。数据库访问使用 Python 标准库 `sqlite3`；前端请求使用原生 `fetch`。

全仓 `mysql` / `sqlalchemy` 字样仅作为**约束陈述**出现在文档中，源码零命中。

---

## 3. 代码规模（不变量）

统计口径：`git ls-files | xargs wc -l`（受版本控制的文件，含文档）。

| 项 | 值 |
|---|---|
| 受版本控制的文件数 | **81** |
| 总行数 | **16334** |

按扩展名分解：

| 扩展名 | 文件数 | 行数 |
|---|---|---|
| `.md`（文档） | 8 | 4874 |
| `.py` | 28 | 4737 |
| `.vue` | 20 | 3565 |
| `.json`（含 `package-lock.json` 1443 行） | 2 | 1443 |
| `.css` | 1 | 357 |
| `.js` | 8 | 320 |
| `.ps1` | 1 | 236 |
| `.yml` | 3 | 231 |
| `.sh` | 1 | 202 |
| 其他（`.gitignore` / `.dockerignore` / `.env.example` / 无扩展名 / `.conf` / `.html` / `.txt`） | 9 | 369 |

注：`package-lock.json` 占 1443 行，是依赖锁文件而非手写代码；扣除文档与锁文件后的手写代码约 9400 行。

---

## 4. 数据库（SQLite，WAL）

### 4.1 结构与配置（不变量）

| 项 | 实测值 |
|---|---|
| 业务表 | **8**（devices / telemetry / ai_chat / alerts / reasoning / commands / weather / skus） |
| 索引 | **7**（`idx_telemetry_device_ts`、`idx_telemetry_ts`、`idx_ai_chat_created`、`idx_alerts_created`、`idx_reasoning_created`、`idx_commands_created`、`idx_weather_plot_ts`） |
| `PRAGMA journal_mode` | **wal** |
| 建表方式 | `CREATE TABLE IF NOT EXISTS` 幂等建表，启动时执行 |
| 写入并发 | 全局单连接 + `threading.RLock` |
| 读取并发 | `threading.local` 独立连接 |
| 库文件 | `/data/agri.db` 63,066,112 B（约 60.1 MiB）；`-wal` 4,140,632 B；`-shm` 32,768 B |

### 4.2 行数（当日快照）

| 表 | 行数 | 增长方式 |
|---|---|---|
| `telemetry` | **153154** | **2880 条/小时**（4 设备 × 每 5 秒一条） |
| `alerts` | **10398** | 随遥测评估产生，受告警冷却去重 |
| `weather` | **9524** | 每地块每 30 秒一条（2 地块 → 240 条/小时） |
| `reasoning` | **52** | 每次推演一条 |
| `ai_chat` | **3** | 每次对话一条 |
| `commands` | **1** | 每次指令一条 |
| `devices` | **4** | 固定清单，不增长 |
| `skus` | **6** | 幂等 seed，不增长 |

遥测时间跨度：`2026-11-01T07:27:00+08:00` → `2026-11-04T11:49:44+08:00`，约 **76.4 小时**。

每小时增量实测（最近 5 个整点）：2880 / 2876 / 2880 / 2880 / 2145（最后一小时未走完）。
**2880 条/小时** 是算术必然（4 设备 × 3600 秒 ÷ 5 秒），因此任何 telemetry 绝对值都会按此速率过期。

### 4.3 推演记录（不变量）

| 项 | 实测值 |
|---|---|
| `reasoning` 条数 | 52 |
| `avg(length(prompt))` | 2184.7 字符 |
| `avg(length(result))` | 2912.4 字符 |
| `source` 分布 | `fallback` × 52（生产未配大模型 Key，全部走本地农学规则库） |

### 4.4 告警分级（当日快照）

| 级别 | 条数 |
|---|---|
| `critical` | 5823 |
| `warning` | 4556 |

---

## 5. 接口与延迟

### 5.1 接口总数（不变量）

**22 条** REST 接口 = 21 个路由装饰器 + `main.py` 的 `GET /api/health`。

V1 共 11 条：`/api/health`、`/api/devices`、`/api/telemetry/latest|history|summary`、`/api/alerts`、`/api/alerts/{id}/ack`、`/api/ai/models`、`/api/ai/chat`、`/api/ai/history`、`/api/meta`。

V2 新增 11 条：`GET|PUT /api/config`、`POST /api/config/test`、`GET /api/models`、`POST /api/reasoning/simulate`、`GET /api/reasoning/history`、`GET /api/reasoning/{id}`、`POST /api/command/execute`、`GET /api/command/history`、`GET /api/weather/latest`、`GET /api/shop/skus`。

### 5.2 延迟（当日快照）

**经公网直连**（本机 → 目标机 8000 端口，单次采样，含公网往返）：

| 接口 | HTTP | 耗时 |
|---|---|---|
| `/api/health` | 200 | 101.7 ms |
| `/api/devices` | 200 | 96.0 ms |
| `/api/meta` | 200 | 69.9 ms |
| `/api/alerts?limit=20` | 200 | 79.6 ms |
| `/api/telemetry/latest` | 200 | 79.1 ms |
| `/api/telemetry/history?device_code=FJ-CITRUS-A01&hours=1` | 200 | 135.3 ms |
| `/api/telemetry/summary?hours=24` | 200 | 113.9 ms |
| `/api/ai/models` | 200 | 59.2 ms |
| `/api/ai/history?limit=10` | 200 | 64.9 ms |
| `/api/reasoning/history?limit=10` | 200 | 62.5 ms |
| `/api/weather/latest` | 200 | 89.5 ms |
| `/api/shop/skus` | 200 | 71.3 ms |

**公网最慢一条 135.3 ms**（曲线接口，返回 720 个点 / 77814 B）。

**服务器内回环**（同一批接口，无公网往返）：全部 **< 32 ms**，最快 1.2 ms（`/api/ai/models`），最慢 31.9 ms（`/api/telemetry/summary?hours=24`）。

### 5.3 一个必须说清的结构性事实（不变量）

`GET /api/telemetry/history` **不是**全量导出接口：`limit` 默认 720、硬上限 5000，语义是「最近 N 个点」。

| 请求 | 实际返回 |
|---|---|
| `hours=24`（默认 limit） | `count=720`，覆盖最近 1 小时 |
| `hours=24&limit=5000` | `count=5000`，覆盖最近约 7 小时 |
| `hours=24&limit=999999` | `count=5000`（被硬上限截断） |

24 小时窗口的**全量统计**由 `/api/telemetry/summary?hours=24` 承担：`samples=69093`，返回温度/湿度/墒情的 avg-min-max，公网 113.9 ms、回环 31.9 ms。

因此「在十几万行上做 24 小时全量查询只要几百毫秒」这个说法，准确表述是：**24 小时窗口的聚合统计扫描 69093 个采样点，公网 114 ms**；曲线接口按设计只回最近 720 点（上限 5000）。

---

## 6. 运行时资源（当日快照）

| 容器 | 状态 | 内存 | CPU |
|---|---|---|---|
| `agri-backend` | Up 15 分钟 (healthy)，`0.0.0.0:8000->8000/tcp` | 58.06 MiB | 0.10% |
| `agri-simulator` | Up 15 分钟 | 19.58 MiB | 0.02% |
| `agri-mosquitto` | Up 2 天，`1883/tcp`（不映射宿主端口） | 3.262 MiB | 0.04% |
| **合计** | 三容器全部 `restarts=0` | **约 80.9 MiB** | — |

宿主 1735 MB 内存下，三容器常驻约占 **4.7%**；Swap 4095 MB 中已用 97 MB。

注：三容器合计内存在 80–95 MiB 区间随负载波动（历史观测到 94 MiB），量级稳定在 **不到 100 MiB**。

宿主侧内存大户并非本项目的容器，而是云厂商自带 agent（AliSecCheck、AliYunDunMonitor、dockerd 各占数十 MB）。

---

## 7. 指令闭环端到端证据（可复核）

### 7.1 指令记录原文

| 字段 | 值 |
|---|---|
| `id` | `cmd_20261102T201552_7d16` |
| `plot_code` / `device_code` | `A` / `FJ-CITRUS-A02` |
| `action` / `params` | `irrigation_on` / `{"duration_min": 30}` |
| `topic` | `agri/command/A/FJ-CITRUS-A02`（QoS 1） |
| `status` | `executed` |
| `created_at` | `2026-11-02T20:15:52+08:00` |
| `ack_at` | `2026-11-02T20:15:52+08:00` |

`created_at` 与 `ack_at` **同一秒**，即回执在同一秒内到达（不是 1.5 秒）。

### 7.2 目标设备确实回升

A02 在回执后 30 秒内的 `soil_moisture` 原始采样（每 5 秒一条）：

```
51.7 → 56.7 → 60.5 → 64.0 → 68.8 → 71.4
```

此后稳定在 72 附近。

### 7.3 定向性证明（同窗口三台对照）

对照窗口：指令前 30 分钟（19:45:52–20:15:52）vs 指令后 30 分钟（20:15:53–20:45:52），取 `soil_moisture` 中位数，已剔除越界注入样本：

| 设备 | 指令前中位数 | 指令后中位数 | 变化 |
|---|---|---|---|
| `FJ-CITRUS-A02`（目标） | 51.2（n=358） | 72.0（n=352） | **+20.8** |
| `FJ-CITRUS-A01` | 57.1（n=356） | 56.2（n=350） | −0.9 |
| `FJ-CITRUS-B01` | 59.8（n=353） | 61.9（n=349） | +2.1 |
| `FJ-CITRUS-B02` | 45.2（n=356） | 46.2（n=348） | +1.0 |

目标设备变化幅度是其余三台的 **10 倍以上**，且方向唯一 —— 这就是「不是广播」的定量证明。

### 7.4 一处必须澄清的数据性质

模拟器按 `SIM_BAD_PROBABILITY=0.12` 注入越界脏数据（`soil_moisture` 正常带 35–80，注入值如 18.0 / 27.0 / 30.5 / 82.0）。

**`30.5` 是注入的越界样本，不是指令前的真实墒情水平。** 用 `30.5` 作为「回升起点」会与「该值属于故障注入」这一设计自相矛盾；正确的起点是**指令前的中位数 51.2**。

上表所有中位数均已剔除越界样本；同窗口内越界样本计数：A01 4 个、A02 5 个、B01 6 个、B02 9 个。

---

## 8. 未验证项与已知偏差（不声称）

| 项 | 状态 |
|---|---|
| 真实大模型成功路径（`source=primary`） | **本次未复跑**；生产未配 Key，52 条推演全部为 `fallback` |
| 并发压测 | 未做 |
| 长跑测试（连续数天观察） | 未做；当前 uptime 2 天 12 小时，`restarts=0` |
| 容器内构建 | 未做（设计上就不在服务器构建） |
| 真实硬件接入 | 未做，全部数据由代码模拟 |
| 公网延迟 | 单次采样，非 P95/P99 |
| 内存数字 | 单次 `docker stats` 快照，非峰值 |

### 8.1 本文修正的三处历史偏差

| 曾出现的说法 | 实测事实 |
|---|---|
| 「24 小时全量查询 278 ms」 | 曲线接口按设计只回最近 720 点（上限 5000）；24 小时**聚合统计**扫描 69093 点，公网 114 ms / 回环 32 ms |
| 「代码里九处 `except Exception`」 | 后端与模拟器源码共 **14 处**，其中 **13 处**带 `# noqa: BLE001`，**8 处**另带中文理由注释；唯一无 `noqa` 的是 `backend/app/db.py:411`（`db_ok()` 探活，异常即返回 `False`） |
| 「墒情从 30.5 回升到 71.4」 | `30.5` 是 `SIM_BAD_PROBABILITY` 注入的越界脏样本；真实起点是指令前中位数 **51.2** |

### 8.2 一处仓库自身的悬空引用（已修复）

`docs/SPEECH_3MIN.md` 曾两处声称「所有数字出自 `docs/PROJECT_AUDIT.md`」，但该文件从未存在于仓库。本文件即为补建，引用自此成立。
