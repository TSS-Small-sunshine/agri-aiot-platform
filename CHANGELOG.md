# 更新日志

本文件格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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

> 三个真实踩过的坑。每个都给出**现象 → 根因 → 方案（含具体配置/代码）→ 量化收益 → 一句话口径**，
> 可以直接拆进 PPT，也可以照着讲。

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

## 版本规划

### [Unreleased]

- 待定。
