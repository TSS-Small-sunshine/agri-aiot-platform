#!/usr/bin/env bash
# ==============================================================================
# 智慧农业 AIoT 平台 —— 裸机开发一键启动（Ubuntu / macOS / MSYS2）
#
# 用法：
#   bash scripts/dev_up.sh                 # 完整流程：装依赖 -> 构建前端 -> 起后端 + 模拟器
#   bash scripts/dev_up.sh --seed          # 额外灌入历史数据（演示大屏趋势曲线用）
#   bash scripts/dev_up.sh --no-sim        # 只起后端，不起模拟器
#   bash scripts/dev_up.sh --stop          # 停掉本脚本启动的后端与模拟器
#
# 幂等：重复执行安全。已存在的 venv / node_modules 不会重建，只做增量安装。
# 日志：logs/backend.log、logs/simulator.log；PID：logs/backend.pid、logs/simulator.pid
# ==============================================================================

set -euo pipefail

# ---- 定位仓库根目录（脚本在 scripts/ 下，根目录是它的上一级）----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

LOG_DIR="${ROOT_DIR}/logs"
VENV_DIR="${ROOT_DIR}/.venv"
STATIC_DIR="${ROOT_DIR}/backend/app/static"
DIST_DIR="${ROOT_DIR}/frontend/dist"

RUN_SEED=0
RUN_SIM=1
DO_STOP=0
for arg in "$@"; do
  case "${arg}" in
    --seed)    RUN_SEED=1 ;;
    --no-sim)  RUN_SIM=0 ;;
    --stop)    DO_STOP=1 ;;
    -h|--help) sed -n '2,16p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "[错误] 未知参数：${arg}（可用：--seed / --no-sim / --stop / --help）" >&2; exit 2 ;;
  esac
done

mkdir -p "${LOG_DIR}"

# ---- 通用小工具 ----
log()  { printf '\033[36m[dev_up]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[警告]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31m[失败]\033[0m %s\n' "$*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "找不到命令 $1。请先安装它（$2），然后重新运行本脚本。"
}

# ---- --stop：先处理停止请求，不做任何安装 ----
stop_one() {
  local name="$1" pidfile="${LOG_DIR}/$1.pid"
  if [[ -f "${pidfile}" ]]; then
    local pid; pid="$(cat "${pidfile}" 2>/dev/null || true)"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
      log "已停止 ${name}（PID ${pid}）"
    else
      log "${name} 未在运行（PID 文件已过期）"
    fi
    rm -f "${pidfile}"
  else
    log "${name} 未在运行（无 PID 文件）"
  fi
}

if [[ "${DO_STOP}" -eq 1 ]]; then
  stop_one backend
  stop_one simulator
  log "完成。"
  exit 0
fi

# ---- 1. 环境检查 ----
need_cmd python3 "Ubuntu: sudo apt install -y python3 python3-venv python3-pip"
need_cmd node    "https://nodejs.org 或 nvm 安装 Node.js 18+"
need_cmd npm     "随 Node.js 一起安装"

PY_VER="$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
log "Python ${PY_VER} / Node $(node --version) / npm $(npm --version)"

# ---- 2. 载入 .env（没有就从 .env.example 复制）----
if [[ ! -f "${ROOT_DIR}/.env" ]]; then
  if [[ -f "${ROOT_DIR}/.env.example" ]]; then
    cp "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
    log "未发现 .env，已从 .env.example 复制一份"
  else
    die "缺少 .env 与 .env.example，请先执行 cp .env.example .env 并填写配置。"
  fi
fi
# shellcheck disable=SC1091
set -a; source "${ROOT_DIR}/.env"; set +a

# 裸机开发没有容器里的 /data 卷，把数据落到仓库本地 ./data，避免写 /data 权限报错
export DB_PATH="${ROOT_DIR}/data/agri.db"
export DATA_DIR="${ROOT_DIR}/data"
# 裸机开发时 broker 跑在本机，而不是 compose 服务名
export MQTT_HOST="${MQTT_HOST:-127.0.0.1}"
[[ "${MQTT_HOST}" == "mosquitto" ]] && export MQTT_HOST="127.0.0.1"
export APP_PORT="${APP_PORT:-8000}"
mkdir -p "${DATA_DIR}"

# ---- 3. Python 虚拟环境 + 依赖 ----
if [[ ! -d "${VENV_DIR}" ]]; then
  log "创建虚拟环境 .venv"
  python3 -m venv "${VENV_DIR}" || die "创建 venv 失败。Ubuntu 需先装 python3-venv：sudo apt install -y python3-venv"
fi
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate" 2>/dev/null || source "${VENV_DIR}/Scripts/activate" \
  || die "激活虚拟环境失败（找不到 activate 脚本）。"
export PIP_DISABLE_PIP_VERSION_CHECK=1

if [[ -f "${ROOT_DIR}/backend/requirements.txt" ]]; then
  log "安装后端依赖（backend/requirements.txt）"
  python -m pip install -q --upgrade pip
  python -m pip install -q -r "${ROOT_DIR}/backend/requirements.txt" \
    || die "安装后端依赖失败。检查网络，或换国内源：python -m pip install -r backend/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple"
else
  warn "未找到 backend/requirements.txt，跳过后端依赖安装（后端负责人尚未提交？）"
fi

if [[ "${RUN_SIM}" -eq 1 ]] && [[ ! -f "${ROOT_DIR}/simulator/mock_sensor.py" ]]; then
  warn "未找到 simulator/mock_sensor.py，模拟器可能无法启动（模拟器负责人尚未提交？）"
fi

# ---- 4. 前端依赖 + 构建 ----
if [[ -f "${ROOT_DIR}/frontend/package.json" ]]; then
  log "安装前端依赖并构建（frontend/）"
  ( cd "${ROOT_DIR}/frontend" && { [[ -d node_modules ]] || npm install; } && npm run build ) \
    || die "前端安装/构建失败。可尝试：cd frontend && rm -rf node_modules && npm install && npm run build"
else
  warn "未找到 frontend/package.json，跳过后端静态资源构建（前端负责人尚未提交？）"
fi

# ---- 5. 把 frontend/dist 拷到 backend/app/static（契约第 7 节）----
if [[ -d "${DIST_DIR}" ]]; then
  log "拷贝前端产物 frontend/dist -> backend/app/static"
  rm -rf "${STATIC_DIR}"
  mkdir -p "${STATIC_DIR}"
  cp -R "${DIST_DIR}/." "${STATIC_DIR}/"
  log "静态资源就绪：$(find "${STATIC_DIR}" -type f | wc -l) 个文件"
else
  warn "frontend/dist 不存在，后端将以「无前端」模式启动（访问 / 会返回一行 JSON 提示）。"
fi

# ---- 6. 可选：灌历史数据 ----
if [[ "${RUN_SEED}" -eq 1 ]]; then
  if [[ -f "${ROOT_DIR}/scripts/seed_history.py" ]]; then
    log "灌入历史数据（scripts/seed_history.py）"
    python "${ROOT_DIR}/scripts/seed_history.py" || die "历史数据灌入失败，请检查 scripts/seed_history.py 的报错。"
  else
    warn "未找到 scripts/seed_history.py，跳过历史数据灌入。"
  fi
fi

# ---- 7. 启动后端与模拟器（后台 + 日志）----
if [[ ! -f "${ROOT_DIR}/backend/app/main.py" ]]; then
  die "找不到 backend/app/main.py，后端无法启动（后端负责人尚未提交？）。"
fi

log "启动后端 uvicorn（端口 ${APP_PORT}），日志 -> logs/backend.log"
( cd "${ROOT_DIR}/backend" && \
  nohup python -m uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT}" \
  > "${LOG_DIR}/backend.log" 2>&1 & echo $! > "${LOG_DIR}/backend.pid" )

# 等后端起来（最多 30 秒）
BACKEND_OK=0
for _ in $(seq 1 30); do
  if python - <<'PY' 2>/dev/null
import os,urllib.request,sys
port=os.environ.get("APP_PORT","8000")
sys.exit(0 if urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health",timeout=2).status==200 else 1)
PY
  then BACKEND_OK=1; break; fi
  sleep 1
done
if [[ "${BACKEND_OK}" -eq 1 ]]; then
  log "后端已就绪：http://127.0.0.1:${APP_PORT}/api/health"
else
  warn "30 秒内未等到 /api/health 返回 200，请查看 logs/backend.log 排查。"
fi

if [[ "${RUN_SIM}" -eq 1 ]] && [[ -f "${ROOT_DIR}/simulator/mock_sensor.py" ]]; then
  log "启动模拟器 mock_sensor，日志 -> logs/simulator.log"
  ( cd "${ROOT_DIR}/simulator" && \
    nohup python mock_sensor.py > "${LOG_DIR}/simulator.log" 2>&1 & echo $! > "${LOG_DIR}/simulator.pid" )
  sleep 1
fi

cat <<EOF

==================================================================
 启动完成
   大屏地址   http://127.0.0.1:${APP_PORT}/
   健康检查   http://127.0.0.1:${APP_PORT}/api/health
   接口文档   http://127.0.0.1:${APP_PORT}/docs
   后端日志   tail -f logs/backend.log
   模拟器日志 tail -f logs/simulator.log
   停止服务   bash scripts/dev_up.sh --stop
==================================================================
EOF
