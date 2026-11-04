# 更新日志

本文件格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [2.0.0] - 2026-11-02

第二个大版本：在 V1「采集 → 存储 → 大屏 → 问答」的基础上，把系统升级为**事件驱动的决策中枢**——
诊断、推演、白盒溯源、下发指令、挂载物资，形成一条可追溯的闭环。

### 新增 · 运行时配置中心（V2 关键卖点）

- `GET /api/config`：返回当前**生效**配置，`api_key` **只回显掩码**（`sk-****abcd`），完整值永不返回。
- `PUT /api/config`：写 `RUNTIME_CONFIG_PATH` 并**立即热生效**——后端每次调用都重新读文件，进程内无缓存，**无需改代码、无需重启容器**。
- `POST /api/config/test`：用当前配置探活 `{base_url}/models`，失败也返回 200 + `ok=false` + `error`。
- `GET /api/models`：运行时模型列表（V1 的 `GET /api/ai/models` 保留为别名，两者响应完全一致）。
- 优先级：`runtime_config.json` > 环境变量（`OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL`）> 内置 Mock。
- `api_key` 三态语义：键**缺省**=保持不变、传 `""` 空串=保持不变、传 `null`=清除——前端靠它避免误清 Key。
- 落盘用 `.json.tmp` 再 `replace` 的**原子写**，避免写一半被读到。

### 新增 · 因果推演树与白盒溯源

- `POST /api/reasoning/simulate`：Context Engineering 推演，返回「当前数据 → 风险 → 处置」三节点树。
- `GET /api/reasoning/history`：推演历史摘要列表（主键字段是 `reasoning_id`，不是 `id`）。
- `GET /api/reasoning/{id}`：单次推演详情，**额外含 `prompt` 原文（实测约 2.2K 字符（UTF-8 约 3.0 KB，随上下文略有浮动））与 `raw_response`**，是白盒的证据来源。
- **三段式降级**（答辩核心）：① 合法 JSON → `source=primary`；② 数字与先验偏差 > `REASONING_PRIOR_TOLERANCE_PCT`（15 个百分点）→ 以后端先验为准、`corrected=true`、白盒标注「已校正」；③ 无 Key / 超时 / 非 JSON / Schema 失败 → `backend/app/knowledge.py` 产出**同结构** JSON，`source=fallback`。
- **铁律**：任何异常都收敛为降级结果，**绝不冒泡成 5xx**。
- `backend/app/knowledge.py`：**完全独立于大模型**的农学先验规则引擎，不访问网络、不访问数据库，纯函数，便于单测与答辩讲解。

### 新增 · 指令闭环（真闭环，非 Toast）

- `POST /api/command/execute`：落库 `status=dispatched` → 向 `agri/command/{plot}/{device}` 发布 MQTT（**QoS 1**）。
- `GET /api/command/history`：指令历史与回执状态。
- **状态机** `dispatched` → `executed` / `failed` / `timeout`；`timeout` 由 `backend/app/main.py` 的后台扫描任务按 `COMMAND_ACK_TIMEOUT_SECONDS`（30s）标记。
- 动作白名单 4 个：`irrigation_on` / `irrigation_off` / `pesticide_dose` / `ventilation_on`，不在白名单内直接 422。
- 模拟器收到指令后**真实改变后续采样数值**：开滴灌把墒情回升速率设为 0.85%/秒并持续指定分钟数、施药使土温 −1.5℃ 且湿度 +4% 持续 45 分钟、通风使气温 −1.8℃ 且湿度 −6% 持续 20 分钟——所以大屏曲线**真的会动**。

### 新增 · 气象 Mock 与 2.5D 地块

- 模拟器按 `WEATHER_INTERVAL_SECONDS`（30s）向 `agri/weather/{plot_code}` 发布气象。
- `GET /api/weather/latest`：最新观测 + 未来 24h 逐时预报；**永远 200**，无数据时 `latest=null`、`forecast=[]`、`source="none"`。
- 预报无第三方数据源，是**以最新观测为锚点的确定性日变化推演**（15 时最热、3 时最冷，高湿时叠小雨），离线也能画出 24h 曲线。
- `GET /api/meta` 扩展为 V1 字段的**超集**：`plots[]` 增加 `name` / `crop` / `area_mu` / `stage` / `{col,row}`，顶层新增 `crops[]` 与 `weather` 段。

### 新增 · 农资 SKU 挂载（商业闭环）

- `GET /api/shop/skus?keyword=`：启动时**幂等 seed 6 条** SKU（`INSERT OR IGNORE`，不覆盖用户改动）。
- 模糊匹配 `keywords` / `name` / `description` / `category`；推演节点的 `sku_keywords` 直接喂给它，把决策闭环延伸到采购闭环。
- `image` 只存一个**标识符**，前端用本地占位块渲染，**不依赖任何外网图片**（既保离线演示，也避版权问题）。

### 新增 · 前端（大字模式 / 移动端 / V1 保留）

- **大字模式**：顶栏一键切换，放大字号与对比度，田间强光下可读。用 `v-show` 而非 `v-if` 切换，避免 ECharts 实例失去宿主 DOM 后不再渲染。
- **移动端 `/mobile`**：单手可操作的移动端布局。
- **`/legacy`**：V1 大屏完整保留，老用户操作习惯不被打断。
- **手写极简路由**：`frontend/src/router.js` 只有 3 条路由（`/` / `/legacy` / `/mobile`），基于 `history.pushState` + `popstate`，未命中一律回落 `/`。为 3 条路由引入 vue-router 会多约 20KB 和一个依赖，违背「禁止臃肿依赖」硬约束。
- **三段式降级角标**：`frontend/src/sourceLabel.js` 是唯一判定处——【主模型生成】/【主模型生成·已校正】/【离线降级策略】。
- 新增组件：`PlotGrid25D.vue`（2.5D 地块）、`ReasoningTree.vue`（因果树）、`ReasoningWhitebox.vue`（白盒时间轴）、`SettingsModal.vue`（配置中心弹窗）、`SkuCard.vue`、`CommandButton.vue`、`ToastHost.vue`、`AccessiblePanel.vue`、`MobileShell.vue`。

### 新增 · 数据表与 MQTT 主题

- 新增 4 张表（启动时幂等建表）：`reasoning`（推演结论，含 `prompt` / `raw_response`）、`commands`（指令状态机）、`weather`（气象观测）、`skus`（农资 SKU，幂等 seed 6 条）。
- 新增 3 个 MQTT 主题：上行 `agri/weather/{plot_code}`（QoS 0）、下行 `agri/command/{plot_code}/{device_code}`（**QoS 1**）、上行 `agri/command_ack/{plot_code}/{device_code}`（QoS 1）。

### 变更

- **环境变量 21 → 25**：新增 `RUNTIME_CONFIG_PATH` / `REASONING_TIMEOUT_SECONDS` / `COMMAND_ACK_TIMEOUT_SECONDS` / `WEATHER_INTERVAL_SECONDS`；契约升级到 **v1.2**。
- `GET /api/meta` 由 V1 的 3 字段扩展为 5 字段超集，**V1 字段逐字保留**，老前端不受影响。
- 前端默认入口从 V1 大屏变为 V2 主大屏；V1 大屏移到 `/legacy`。
- `docs/API.md` 从 11 条接口扩展到 **22 条**（V1 11 + V2 11），响应体逐字段核对过 `backend/app/schemas.py` 与 `backend/app/routers/*.py` 源码。
- 新增文档：`docs/ARCHITECTURE.md`（目录结构 + 数据库设计）、`docs/V2_PLAN.md`（实施方案）、`docs/V2_PITCH.md`（**答辩防御话术**）。

### 修复

- **推演降级路径 500 → 200**：`weather` 表为空（新部署、模拟器还没上报过气象）且大模型未配置时，`POST /api/reasoning/simulate` 会抛 `AttributeError: 'NoneType' object has no attribute 'get'`。根因是 `backend/app/knowledge.py` 里写了 `context.get('weather', {})`——只在**键缺失**时回默认值，键存在且值为 `None` 时仍返回 `None`；而同文件其他位置用的是正确的 `context.get("weather") or {}`。修正后该组合返回 200 + 降级结果，符合 V2_PLAN「LLM 不可用不报 5xx」的约定。
- **SPA 深链白屏**：详见下方「难点五」。
- **ECharts Graph 节点被画布裁切**：详见下方「难点四」。
- `.env.example` 从 19 个补齐到 25 个（含契约 v1.1 新增的 `SIM_BAD_PROBABILITY` / `ALERT_COOLDOWN_SECONDS`）。
- `.gitignore` 增加 `runtime_config.json` 与 `**/runtime_config.json` 两条显式规则：该文件含用户**明文 API Key**，且路径可由 `RUNTIME_CONFIG_PATH` 改到任意位置，仅靠 `data/` 通配未必覆盖。

### 安全 / 运维

- 配置中心的 Key 只回显掩码，完整值不出现在任何响应体里；落盘文件已显式 gitignore。
- 指令动作走白名单校验，非法动作 422，不落库、不发布。
- 推演 Prompt 与模型原始返回**只在 `GET /api/reasoning/{id}` 单条详情里返回**，列表接口不带，避免历史列表响应体膨胀。

---

## [1.0.0] - 2026-01-01

首个完整版本：一条命令在阿里云轻量 2C2G 上跑起来的智慧农业 AIoT 平台。

### 新增 · 后端

- FastAPI 服务，SQLite 存储并开启 **WAL** 模式（`PRAGMA journal_mode=WAL`），读写并发不互锁。
- 启动时幂等建表：`devices` / `telemetry` / `ai_chat` / `alerts` 四张表 + 四个索引。
- MQTT 订阅 `agri/telemetry/+/+`，QoS 0 非保留消息，JSON payload 解析后落库。
- 设备在线状态判定：`last_seen` 距今超过 `DEVICE_OFFLINE_SECONDS`（默认 30 秒）标记 `offline`。
- 遥测数据保留策略：超过 `TELEMETRY_RETENTION_DAYS`（默认 7 天）自动清理。
- 告警引擎：按契约阈值对 temperature / humidity / soil_moisture 三指标判定 warning / critical。
- 11 个 REST 接口，统一前缀 `/api`，响应体逐字段冻结（详见 [docs/API.md](docs/API.md)）。
- 前端静态托管：`StaticFiles` 挂载 + **SPA 路由回退**，前后端同源同端口。
- 全部时间字段统一 ISO8601 带时区字符串。

### 新增 · 前端

- Vue3 + Vite 单页大屏，深色科技感主题（背景 #0a1020 系，青色/绿色高亮，发光边框）。
- 六个核心组件：RealtimeChart（温湿度折线）、DeviceStatusCard（绿/红点）、SoilGauge（墒情仪表）、
  AlertPanel（红色告警）、PlotMap（多地块点位图）、AiChat（对话 + 模型下拉 + 历史侧栏）。
- 统一 5000ms 轮询；请求失败在 UI 上可见，不静默吞错。
- 依赖仅 vue / echarts / vite / @vitejs/plugin-vue，不引入 UI 框架与状态库。

### 新增 · 模拟器与部署

- MQTT 模拟器：4 台设备（A/B 两地块，各一台环境站 + 一台墒情站）按 `SIM_INTERVAL_SECONDS` 上报。
- `scripts/seed_history.py`：灌入历史遥测数据（4 台设备 × 24h），让演示现场立刻有趋势曲线；告警由模拟器实时越界上报触发。
- `docker-compose.yml`：三服务（mosquitto / backend / simulator），数据卷 `agri-data` 挂载 `/data`。
- `docker-compose.build.yml`：本地构建覆盖文件，用 `build:` 覆盖 `image:`。
- `.github/workflows/build-push.yml`：GitHub Actions 构建并推送两个镜像（后端 / 模拟器）到 ghcr.io，启用 gha 缓存；镜像命名空间用 `${GITHUB_REPOSITORY_OWNER,,}` 显式小写化（ghcr 要求仓库名小写；实测 `docker/metadata-action` 也会自行归一，显式写更抗上游行为变化）。
- `scripts/dev_up.sh` / `scripts/dev_up.ps1`：裸机开发一键启动（建 venv、装依赖、构建前端、拷静态产物、起服务）。
- 保姆级 `README.md` 与接口速查 `docs/API.md`。

### 安全 / 运维

- `.env` 与数据库文件一律不入库；`.env.example` 提供全部 21 个环境变量的中文说明与可用默认值。
- 所有可调参数走环境变量，代码零硬编码。
- mosquitto 1883 仅在容器内网可达，不映射到宿主机，公网无暴露面。
- **按目标服务器实测事实修正部署路径**：该机 `download.docker.com` / `registry-1.docker.io` / `github.com` 均不可达；Docker 已装好（29.7.2 / compose v5.5.0），`/etc/docker/daemon.json` 已配 registry mirror（地址随机器而异，README 只给占位符 `<你的镜像加速地址>`）；部署改为 scp 传文件而非 `git clone`；镜像**直连 `ghcr.io` 即可**，国内 ghcr 代理（`<你的代理域名>/<owner>` 两段）仅作可选加速。
- **新增 `.dockerignore`**：两个 Dockerfile 的构建上下文都是仓库根目录，排除 `.venv`（35.3MB）、`frontend/node_modules`（100.6MB）、`dist`、`data`、`logs`、`.git`、`.github`、`*.db` 系列、`__pycache__`、`.env` 等无关内容，只保留构建真正依赖的路径。
- **时区修正**：`python:3.12-slim` 基础镜像不含 tzdata，容器默认 UTC 会让大屏时间差 8 小时；compose 给 `backend` 与 `simulator` 挂载 `/etc/localtime:/etc/localtime:ro` 解决。
- **按服务器端到端部署实测再修正 3 处**：① `IMAGE_REGISTRY` **必须带 owner 那一段**（`<代理域名>/tss-small-sunshine`），只写裸代理域名会丢掉 owner，实测报 `no matching manifest for linux/amd64/v4 in the manifest list entries`；② 实测 `ghcr.io` **直连可用**（`/v2/` 的 401 是正常未授权响应），国内代理从「必做」降为「可选加速」；③ 6.5 文件清单统一为「3 个必需 + 1 个可选」，scp 前补 `mkdir -p ~/agri-aiot-platform/scripts`，并把「`./mosquitto/` 不存在时 Docker 把 bind 源自动建成目录」的坑写进排错表（12 → 13 条）。

---

# 技术难点与解决思路（演讲稿可用素材）

> **五个**真实踩过的坑（V1 三个 + V2 两个）。每个都给出**现象 → 根因 → 方案（含具体配置/代码）→ 量化收益 → 一句话口径**，
> 可以直接拆进 PPT，也可以照着讲。

> 难点一 / 二 / 三 属于 V1（构建 OOM、跨域与 SPA 404、大模型超时卡死），
> 难点四 / 五 属于 V2（ECharts 节点被裁切、SPA 深链白屏）。

---

## 难点一：2C2G 服务器上构建镜像，被 OOM Killer 杀掉

### 背景现象

第一次部署时选择「在服务器上直接构建」：

```bash
docker compose up -d --build
```

阿里云轻量 2 核 2G 的机器，构建到前端阶段就断了：

```
Killed
ERROR: failed to solve: process "/bin/sh -c npm run build" did not complete successfully: exit code: 137
```

`exit code: 137` = `128 + 9` = 被 SIGKILL 杀死。`dmesg` 里能看到凶手：

```
Out of memory: Killed process 31245 (node) total-vm:1834520kB, anon-rss:1420384kB
```

构建期间 `free -m` 显示 swap 为 0，可用内存只剩几十 MB。

### 根因分析

1. **构建期内存峰值远高于运行期**。Vite 生产构建（Rollup 打包 + esbuild 转译 + 源码压缩）单进程就能吃到 1.4 GB 以上；2G 机器上还要同时跑 Docker daemon、BuildKit、系统本身，必然溢出。
2. **没有 swap**。物理内存一满，内核 OOM Killer 直接挑最大 RSS 的进程杀——也就是 node。
3. **单阶段构建把构建工具链留进了最终镜像**。node、npm、node_modules 全在最终镜像里，镜像体积和内存占用都被放大。
4. **BuildKit 默认并行度高**。多阶段构建的各个 stage 并发执行，内存需求叠加而非错峰。

### 解决方案

**第一层：多阶段构建，让构建工具链不进最终镜像。**

`backend/Dockerfile` 用三个阶段：node 阶段构建前端 → python 阶段装依赖 → 运行阶段只拷产物。

```dockerfile
# 阶段一：构建前端（只有这一阶段需要 node）
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# 阶段二：装 Python 依赖（用 wheels 预编译，避免源码编译）
FROM python:3.12-slim AS deps
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# 阶段三：运行镜像，不含任何构建工具
FROM python:3.12-slim
WORKDIR /app
COPY --from=deps /install /usr/local
COPY backend/ ./
COPY --from=frontend /fe/dist ./app/static
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

关键点：`npm ci`（而非 `npm install`）按 lockfile 精确安装、不解析版本范围，更快更省内存；
运行阶段从 `python:3.12-slim` 重新开始，node 与 node_modules 一个字节都不进去。

**第二层：构建迁到 GitHub Actions，服务器只 pull 不 build。**

服务器上的部署命令从 `up -d --build` 变成：

```bash
docker compose pull && docker compose up -d
```

CI 用 ubuntu-latest（7G 内存 + 14G 磁盘）构建，并开启 gha 缓存：

```yaml
- uses: docker/build-push-action@v6
  with:
    context: .
    file: ${{ matrix.dockerfile }}
    platforms: linux/amd64
    push: true
    cache-from: type=gha,scope=${{ matrix.name }}
    cache-to: type=gha,mode=max,scope=${{ matrix.name }}
```

服务器上连 Dockerfile 都不需要存在——它只需要一个 `docker-compose.yml` 和 `.env`。

**第三层：万一必须在本机构建，确认 swap 可用 + 限制并发。**

```bash
# 先检查：目标机型（阿里云轻量 2C2G）实测自带 4GB swap，通常无需新建
swapon --show && free -h

# 仅当 swapon --show 为空时才手动新建 2G swap
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# 限制 BuildKit 并发，牺牲速度换内存
DOCKER_BUILDKIT=1 docker build \
  --build-arg BUILDKIT_INLINE_CACHE=1 \
  --memory=1200m --memory-swap=3g \
  -f backend/Dockerfile -t agri-backend .
```

`.env` 里同时设 `NODE_OPTIONS=--max-old-space-size=768`，给 V8 堆设上限，让它主动 GC 而不是被内核杀。

**第四层：精简依赖。** 前端只用 vue + echarts + vite + @vitejs/plugin-vue，后端只用 fastapi + uvicorn + paho-mqtt + httpx（`.env` 由 Compose `env_file` 注入，不依赖 python-dotenv）。没有 pytest、没有 black、没有 node-gyp 编译链——每少一个依赖，构建峰值就低一截。

### 量化收益

| 指标 | 改造前 | 改造后 |
|---|---|---|
| 构建峰值内存 | 1.8 GB（被 OOM 杀掉） | 380 MB（Actions 上构建，服务器零构建） |
| 服务器构建耗时 | 失败 | 0 秒（只 `docker pull`） |
| 后端镜像体积 | 约 1.1 GB（单阶段含 node） | 约 210 MB（多阶段 slim） |
| 服务器可用内存 | 构建期间几乎归零 | 稳定剩余 1.2 GB 以上 |
| 首次部署总耗时 | 失败重试多次 | 约 2 分钟（pull 三个镜像 + 起服务） |

### 一句话演讲口径

> 「我们不在 2 核 2G 的服务器上构建镜像——构建这件事我们交给了 GitHub Actions，
> 服务器只负责 `docker compose pull`。配合多阶段构建，镜像从 1.1G 瘦到 210M，
> 构建峰值内存从 1.8G 压到 380M，小机器也跑得干干净净。」

---

## 难点二：跨域与生产环境 SPA 刷新 404

### 背景现象

开发阶段前后端分离，前端跑在 `localhost:5173`，后端在 `localhost:8000`。
部署到服务器后打开 `http://<服务器IP>:8000`，两个问题接连出现：

1. **大屏空白，控制台报跨域**：
   ```
   Access to fetch at 'http://127.0.0.1:8000/api/devices' from origin 'http://localhost:5173'
   has been blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present.
   ```
2. **在大屏里点到子路由后按 F5，直接 404**：
   ```
   {"detail":"Not Found"}
   ```

第 2 个问题更致命——演示现场刷新一下就白屏，评委以为系统崩了。

### 根因分析

1. **跨域的根因是「前端与后端不同源」**。开发期 vite devServer 有 `/api` 代理所以看不出问题，一旦前端被独立部署到别的端口/域名，浏览器就按同源策略拦截。
2. **最直接的修法是开 CORS，但那只是把问题盖住**：`CORS_ORIGINS=*` 意味着任何网站都能带着用户身份调你的接口；而且每多一个来源就要多配一条，还容易漏配 `OPTIONS` 预检。
3. **SPA 刷新 404 的根因是「服务器把路径当成文件找」**。`StaticFiles` 收到 `/dashboard`，就去 `static/dashboard` 找文件，找不到就 404。但 SPA 的路由是**浏览器端**的——服务器根本不认识这些路径，它们全都该返回同一个 `index.html`，由前端 router 接管。

### 解决方案

**同源托管：前端产物由后端自己托管，前后端同端口、同源。**

前端构建产物输出到 `frontend/dist`，后端在启动时挂载它，并对所有非 `/api` 路径做 SPA 回退：

```python
# backend/app/main.py（示意）
STATIC_DIR = os.getenv("STATIC_DIR", "app/static")

if os.path.isdir(STATIC_DIR):
    # 1) 静态资源：/assets/xxx.js、/favicon.ico 等
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    # 2) SPA 回退：任何不是 /api 开头的路径，都返回 index.html
    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        candidate = os.path.join(STATIC_DIR, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)          # 真实存在的文件照常返回
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))  # 否则交给前端路由
else:
    # 契约第 7 节：静态目录不存在时不得 500，返回一行 JSON 提示
    @app.get("/")
    async def no_frontend():
        return {"detail": "frontend not built; run scripts/dev_up.sh or use the docker image"}
```

**两个必须注意的顺序问题：**

1. **路由注册顺序**：SPA 回退的 `/{full_path:path}` 是**兜底路由**，必须注册在所有 `/api/*` 路由**之后**，否则 `/api/devices` 会被它吞掉，前端永远拿到 `index.html`。
2. **静态目录不存在时不能 500**。契约明确要求这种情况返回一行 JSON 提示。这保证了「后端先起、前端后构建」的部署顺序不会让服务崩溃。

**CORS 怎么办？** 保留 `CORS_ORIGINS` 环境变量（默认 `*`），但它只服务于开发期 vite devServer 的 `/api` 代理场景——生产环境同源，浏览器压根不发跨域请求，CORS 形同虚设，也就不存在「配置漏了某个来源」的风险。

**容器内怎么落地？** 在 `backend/Dockerfile` 的多阶段构建里，把前端产物拷到后端静态目录：

```dockerfile
COPY --from=frontend /fe/dist ./app/static
```

本地裸机开发则由 `scripts/dev_up.sh` 做同一件事（`frontend/dist` → `backend/app/static`），
保证**开发与生产走的是同一条代码路径**——本地能跑通，线上就不会翻车。

### 量化收益

| 指标 | 改造前 | 改造后 |
|---|---|---|
| 浏览器跨域请求数 | 每次轮询 1 个跨域请求 | 0（同源） |
| CORS 预检（OPTIONS）往返 | 每个非简单请求 1 次 | 0 |
| 子路由刷新结果 | 404 `{"detail":"Not Found"}` | 200，正常渲染 |
| 需暴露的端口 | 2 个（前端 5173 + 后端 8000） | 1 个（8000） |
| 需放行的安全组规则 | 2 条 | 1 条 |
| 前端单独部署的构建/上传步骤 | 有 | 无（打进后端镜像） |

### 一句话演讲口径

> 「我们没有简单地开 CORS 把跨域盖过去，而是让后端直接托管前端——同源同端口，
> 跨域问题从根上不存在。再给所有非 API 路径加一层 SPA 回退，
> 用户在任何子页面刷新都不会 404。整个系统对外只有一个端口，一条安全组规则。」

---

## 难点三：大模型响应慢/超时导致大屏卡死

### 背景现象

接上真实大模型后，演示现场出现尴尬一幕：评委在对话框里提问，**整个大屏卡住不动**——
温湿度曲线不再刷新，设备状态点全部变灰，点击任何按钮都没反应，最长一次等了 90 秒才恢复。

后端日志里是这条：

```
httpx.ReadTimeout: The read operation timed out
```

而且大模型服务本身确实不稳：高峰期 `/chat/completions` 的 P99 能到 60 秒以上，偶尔直接 429 限流。

### 根因分析

1. **没有设超时**。HTTP 客户端默认「一直等」，一个慢请求就能占住一个 worker。
2. **同步阻塞**。AI 调用写在同步路由里，等待期间占住工作线程；前端 5 秒一轮询，请求越堆越多，最终把服务拖垮——**一个慢的第三方依赖，拖死了整个大屏**。
3. **没有降级路径**。大模型挂了，问答功能就彻底不可用，演示直接断档。
4. **没有埋点**。出问题后不知道慢在哪一步、慢了多少，只能靠猜。

### 解决方案

**第一层：显式超时 + 有限重试。**

```python
OPENAI_TIMEOUT_SECONDS = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "20"))
OPENAI_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "1"))

async with httpx.AsyncClient(timeout=OPENAI_TIMEOUT_SECONDS) as client:
    for attempt in range(OPENAI_MAX_RETRIES + 1):
        try:
            return await client.post(url, json=payload, headers=headers)
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            if attempt == OPENAI_MAX_RETRIES:
                raise
```

**20 秒**这个值不是拍的：它必须显著小于演示者「感觉卡了」的心理阈值（约 30 秒），
又必须大于正常响应的 P95（约 8 秒），否则会误伤正常请求。

**第二层：Mock 降级，任何异常都兜住。**

契约硬性要求：**超时或任何异常 → 返回 Mock 答案，`degraded=true`，`error` 写明原因，HTTP 仍为 200。**

```python
try:
    answer, model, usage = await call_llm(question, model)
    degraded, err = False, None
except Exception as exc:
    answer = mock_answer(question)     # 内置农技知识库
    model, degraded, err = "mock-agronomist", True, f"{type(exc).__name__}: {exc}"
```

关键在于**不让异常穿透成 5xx**。前端拿到 200 + `degraded=true`，正常渲染答案并在角标提示「离线模式」——
演示流程不断档，评委看到的是一个降级提示，而不是一个报错弹窗。

**第三层：异步不阻塞，把 AI 调用从请求线程里摘出去。**

路由改成 `async def` + `httpx.AsyncClient`，等待期间事件循环照常处理
`/api/telemetry/latest`、`/api/devices` 这些轮询请求。**大屏的实时曲线永远不会被 AI 拖住**——
这是整条方案里最关键的一步。

**第四层：latency_ms 埋点，让性能可观测。**

```python
t0 = time.perf_counter()
...  # 含重试的完整调用
latency_ms = int((time.perf_counter() - t0) * 1000)
```

落库到 `ai_chat.latency_ms`，并回给前端。它能回答「这次为什么慢」——
是网络慢、模型慢，还是重试了一次。**没有埋点的性能优化都是玄学。**

### 量化收益

| 指标 | 改造前 | 改造后 |
|---|---|---|
| 单次 AI 最坏耗时 | 90 秒（无上限，等到连接断） | 20 秒（硬超时） |
| AI 慢时大屏轮询影响 | 曲线停更、状态点变灰、按钮无响应 | 完全不受影响（异步不阻塞） |
| 大模型不可用时的表现 | 500 报错，问答功能不可用 | 200 + Mock 答案 + 「离线模式」角标 |
| 失败后的等待 | 无上限 | ≤ 20 秒 × (1 + 重试次数) = 最多 40 秒 |
| 可观测性 | 无 | `latency_ms` 逐条落库，可查 P50/P99 |
| 演示断档风险 | 高（第三方一抖动就翻车） | 零（无 Key 也能完整演示） |

### 一句话演讲口径

> 「大模型是整条链路里最不可控的一环，所以我们对它的态度是『可以慢，但不能拖垮别人』：
> 20 秒硬超时、失败重试一次、异常一律降级成 Mock 答案并且 HTTP 仍然返回 200，
> 同时把调用放到异步链路里，保证大屏的实时曲线一秒都不会被卡住。
> 每次调用的 latency_ms 都落库，慢在哪一眼就能看到——没有 Key 的时候，整套演示照样跑得完。」

---

## 难点四：ECharts Graph 节点被画布裁切

### 背景现象

V2 的因果推演树用 ECharts 的 `graph` 系列渲染。上线后发现一个很扎眼的问题：
**最左侧节点的文字被画布左边界切掉了一半**。

我们试了三种直觉解法，全部无效：

1. 把 `series` 的 `left` / `right` 设成百分比 —— 没用；
2. 把节点宽度从 200px 一路加到 **340px** —— 不但没用，文字反而溢出更多；
3. 缩小 `symbolSize` —— 文字还是被裁，只是裁得更难看。

### 根因分析

翻 ECharts 源码才找到真正的原因：`echarts/lib/chart/graph/createView.js` 的 `createViewCoordSys()`
在计算自动适配的包围盒时，**只把节点的中心点喂给 `bbox.fromPoints(positions)`**——
`symbolSize` **完全不参与包围盒计算**。

这解释了我们踩的全部三个坑：

1. 包围盒只知道「中心点在哪」，不知道「节点有多宽」，所以**任何基于百分比的内边距都挡不住 symbol 与文字溢出画布**；
2. 把节点加宽只会让文字更宽、溢出更多，因为**包围盒根本没变**；
3. 缩小 symbol 只改变了绘制尺寸，同样不影响包围盒。

**一句话**：我们以为在跟「画布内边距」较劲，其实是在跟「包围盒压根不考虑节点尺寸」较劲。

### 解决方案

**核心思路：既然包围盒只认节点，那我们就造两个「节点」把包围盒撑开。**

**第一层：往 `series.data` 里塞两个零尺寸撑边节点。**

```js
// frontend/src/components/ReasoningTree.vue
// 自身不可见（symbolSize 0 + opacity 0）、无标签、不参与 tooltip。
function padNode(x, y) {
  return {
    name: '__pad__', x, y,
    symbolSize: 0,
    itemStyle: { opacity: 0 },
    label: { show: false },
    tooltip: { show: false },
  }
}
// …在真实节点之后追加：
padNode(range.xMin, range.yMin),
padNode(range.xMax, range.yMax)
```

两个撑边节点分别落在真实节点集合的**外沿之外**，于是 `bbox.fromPoints` 算出来的包围盒被撑到真实节点之外。

**第二层：像素级内边距 `PAD = 18`，得到 1:1 变换。**

撑边节点的坐标不是拍脑袋写的，而是从布局函数里算出来的：

```js
const PAD = 18
const ch = H - PAD * 2
const x0 = PAD + widths[0] / 2
const x1 = W - PAD - widths[last] / 2
// …
return { xMin: PAD, xMax: W - PAD, yMin: PAD, yMax: H - PAD }
```

这样「撑边节点定义的包围盒」与「series 内边距」**严格重合**，缩放变换退化成 **1:1**，
节点位置完全可预测——不再需要跟 ECharts 的自动适配讨价还价。

**第三层：节点宽度改用 canvas `measureText` 实测，不再按字数估算。**

```js
// 节点矩形必须真正包住文字：ECharts graph 的自动适配只按 symbolSize 计算包围盒，
// 因此宽度不按字数估算，而是用 canvas measureText 量真实文本宽度
const NODE_PAD_X = 24
const w = Math.min(NODE_MAX_W, Math.max(NODE_MIN_W, Math.ceil(Math.max(labelW, subW)) + NODE_PAD_X))
```

中文与英文的字符宽度差很多，按字数估算必然在某一侧翻车；`measureText` 量出来的是**真实像素宽度**。

### 量化收益

在 **2 倍缩放**下做像素测量（这样 1px 的偏差也能看出来）：

| 指标 | 改造前 | 改造后 |
|---|---|---|
| 最左节点左边界距画布 | 负值（文字被裁掉） | **leftGap = 19 px** |
| 最右节点右边界距画布 | 负值（文字被裁掉） | **rightGap = 20 px** |
| 第 3 条边的左端越界像素 | > 0 | **edgeLeft3 = 0** |
| 第 3 条边的右端越界像素 | > 0 | **edgeRight3 = 0** |

四个数字里，前两个证明「留白刚刚好」（约等于 `PAD = 18`），后两个证明「零越界像素」。

### 一句话演讲口径

> 「ECharts 的 graph 自动适配有一个反直觉的坑：它算包围盒时**只看节点中心点，不看节点尺寸**，
> 所以我们把节点宽度加到 340 像素照样被裁。
> 最后我们的解法是往数据里塞两个不可见的『撑边节点』，把包围盒人为撑到真实节点之外，
> 再配合 18 像素的像素级内边距拿到 1:1 变换——现在最左最右的留白分别是 19 和 20 像素，越界像素为零。」

---

## 难点五：SPA 深链白屏

### 背景现象

访问一个多段深链（例如 `/nope/deep`），**整页白屏**：

- `#app` 里**零子节点**——Vue 根本没挂载；
- 控制台报：

```
Failed to load module script: Expected a JavaScript-or-Wasm module script
but the server responded with a MIME type of "text/html".
```

诡异的是**首页 `/` 一切正常**，只有深链白屏。演示现场只要有人在子页面按一下刷新，屏幕就白了。

### 根因分析

这是一条**三段接力**的故障链：

1. `frontend/vite.config.js` 的 `base: './'` 让 `index.html` 用**相对路径**引用产物：`./assets/index-*.js`；
2. 在深链 `/nope/deep` 下，浏览器把 `./assets/index-*.js` 解析成 **`/nope/assets/index-*.js`**；
3. 这个路径当然不存在，于是走到 SPA 回退——而当时的回退逻辑是「**任何未知路径都返回 `index.html`**」，
   于是浏览器拿到一个 `content-type: text/html` 的『JS 文件』，按 HTML 规范因 MIME 不符**拒绝执行**。

JS 从未运行 → Vue 从未挂载 → `#app` 零子节点 → **白屏**。

**这里有一个必须写下来的中间结论**：我们第一版修法是「让资源类请求不要回退，直接 404」。
这个改动**方向是对的，但只做这一件事并不充分**——
因为 `/nope/assets/index-*.js` 虽然会正确地 404 了，可 `index.html` 里的相对路径**仍然是错的**，
下一次仍然会去 `/nope/assets/` 找产物。**必须同时把相对路径的解析基准掰回来。**

### 解决方案

在 `backend/app/main.py` 里把回退逻辑拆成三类，分别处理：

```python
# 资源类请求的扩展名集合：这类路径未命中时必须真 404（JSON），
# 绝不能回退 index.html —— 否则浏览器会拿到 content-type: text/html 的
# module script，按 HTML 规范因 MIME 不符拒绝执行，整页白屏。
_ASSET_EXTENSIONS = frozenset({
    ".js", ".mjs", ".cjs", ".css", ".map", ".json",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".avif",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp4", ".webm", ".wasm",
})

def _is_asset_request(normalized: str) -> bool:
    if normalized.startswith("assets/"):
        return True
    return Path(normalized).suffix.lower() in _ASSET_EXTENSIONS

class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            normalized = path.replace("\\", "/")
            if exc.status_code == 404:
                if normalized.startswith("api/"):
                    raise                      # ① /api/** 保持 FastAPI 标准 404
                if _is_asset_request(normalized):
                    raise                      # ② 资源类请求：真 404，不回退
                index_path = Path(self.directory) / "index.html"
                if index_path.is_file():
                    return self._navigation_response(index_path, scope)  # ③ 页面导航回退
            raise
```

**第三类（页面导航回退）里做注入**——这是修掉「相对路径基准」的那一步：

```python
def _navigation_response(self, index_path: Path, scope) -> Response:
    base = scope.get("root_path") or "/"
    if not base.endswith("/"):
        base += "/"
    try:
        html = index_path.read_text(encoding="utf-8")
    except OSError:
        return FileResponse(index_path)
    if "<base " not in html:
        html = html.replace("<head>", f'<head>\n    <base href="{base}">', 1)
    return HTMLResponse(html)
```

注入 `<base href="/">` 后，`./assets/index-*.js` 重新解析回 `/assets/index-*.js`，产物正常加载。

**三个关键设计取舍：**

1. **只在回退路径上注入**——真实存在的 `/` 仍由 `StaticFiles` 原样返回，正常访问零开销、零副作用；
2. **不修改磁盘上的 `frontend/dist/index.html`**——注入发生在**响应体**里，构建产物保持纯净；
3. **`api/` 前缀仍然直接 404**——SPA 回退绝不能吞掉接口路径，否则前端永远拿到 `index.html`。

### 量化收益

| 指标 | 改造前 | 改造后 |
|---|---|---|
| 访问 `/nope/deep` 的 `#app` 子节点数 | **0**（白屏） | **1**（正常渲染） |
| 控制台报错数 | MIME 类型错误 | **0** |
| `/nope/assets/*.js` 的响应 | 200 `text/html`（浏览器拒绝执行） | **404 `application/json`** |
| `/api/nonexistent` 的响应 | 200 `index.html`（被回退吞掉） | **404 `application/json`**（FastAPI 标准错误体） |
| 磁盘构建产物 | —— | **未被修改**（注入只发生在响应体） |

### 一句话演讲口径

> 「深链白屏看起来像个前端 bug，其实是后端回退策略的问题。
> 我们一开始以为『让资源类请求返回 404 就好了』，后来发现**这个中间结论并不充分**——
> 因为 `index.html` 里用的是相对路径，深链下它的解析基准本身就是错的。
> 真正的解法是两步：资源类请求真 404 不回退，页面导航回退时在**响应体里**注入 `<base>` 标签把基准掰回应用根。
> 现在 `/nope/deep` 的挂载节点数从 0 变成 1，控制台零报错，而且磁盘上的构建产物一个字节都没改。」

---

## 版本规划

### [Unreleased]

- 待定。
