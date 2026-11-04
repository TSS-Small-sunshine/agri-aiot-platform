<template>
  <div class="ms-wrap">
    <!-- 手机外壳：圆角边框 + 刘海/状态条 -->
    <div class="ms-phone">
      <div class="ms-notch"></div>
      <div class="ms-statusbar">
        <span class="mono">{{ clock }}</span>
        <span class="ms-sig">
          <i class="ms-bar"></i><i class="ms-bar"></i><i class="ms-bar"></i>
          <b class="ms-batt mono">{{ batteryPct }}</b>
        </span>
      </div>

      <div class="ms-screen">
        <header class="ms-head">
          <div class="ms-title">
            <h1>智慧农业 · 移动端</h1>
            <p class="ms-sub">福建省南平市 · 柑橘示范园</p>
          </div>
          <button class="ms-back" type="button" @click="go('/')">返回决策中枢</button>
        </header>

        <p v-if="errors.length" class="ms-err">接口异常：{{ errors.join(' ｜ ') }}</p>

        <!-- ① 拍照识病 -->
        <section class="ms-card">
          <div class="ms-card-title"><span class="bar"></span>拍照识病</div>
          <div class="ms-shot">
            <!-- 无摄像头：用占位图标说明，不假装拍照成功 -->
            <div class="ms-shot-ph">
              <span class="ms-shot-icon">🌿</span>
              <span class="ms-shot-tip">无摄像头设备 · 演示用占位图</span>
            </div>
          </div>
          <button class="ms-cta" type="button" :disabled="diseaseLoading" @click="askDisease">
            {{ diseaseLoading ? '识别中…' : '拍照识病 · 立即问诊' }}
          </button>

          <div v-if="diseaseError" class="ms-err">{{ diseaseError }}</div>
          <div v-if="diseaseMsg" class="ms-bubble">
            <div class="ms-bubble-head">
              <span class="tag" :class="diseaseTag.kind">{{ diseaseTag.text }}</span>
              <span class="mono ms-meta">{{ diseaseMsg.model || '--' }} · {{ diseaseMsg.latency_ms ?? '--' }}ms</span>
            </div>
            <p class="ms-q">{{ diseaseMsg.question }}</p>
            <p class="ms-a">{{ diseaseMsg.answer }}</p>
          </div>
        </section>

        <!-- ② 地块数据卡片 -->
        <section class="ms-card">
          <div class="ms-card-title"><span class="bar"></span>地块数据</div>
          <div v-if="metaLoading" class="ms-skeleton"></div>
          <div v-else-if="!plotCards.length" class="ms-empty">暂无地块数据</div>
          <div v-else class="ms-plots">
            <div v-for="p in plotCards" :key="p.plot_code" class="ms-plot">
              <div class="ms-plot-head">
                <b>{{ p.name }}</b>
                <span class="mono ms-plot-code">{{ p.plot_code }} · {{ p.crop }}</span>
              </div>
              <!-- 指标按地块 metrics 渲染：C 区菇棚是棚温·湿度·CO₂，不会出现「墒情 --」 -->
              <div class="ms-metrics">
                <span v-for="m in p.metrics" :key="m" class="ms-metric">
                  <i>{{ metricLabel(m) }}</i><b class="mono">{{ num(p[m]) }}{{ metricUnit(m) }}</b>
                </span>
                <span class="ms-metric"><i>电量</i><b class="mono">{{ num(p.battery) }}%</b></span>
              </div>
              <p class="ms-plot-foot mono">在线 {{ p.online }}/{{ p.devices }} · 数据时间 {{ shortTs(p.ts) }}</p>
            </div>
          </div>
        </section>

        <!-- ③ 待办任务 -->
        <section class="ms-card">
          <div class="ms-card-title">
            <span class="bar"></span>待办任务
            <span class="sub">{{ todos.length }} 条待确认</span>
          </div>
          <div v-if="todosLoading" class="ms-skeleton"></div>
          <div v-else-if="!todos.length" class="ms-empty">暂无待确认告警 ✓</div>
          <ul v-else class="ms-todos">
            <li v-for="a in todos" :key="a.id" class="ms-todo" :class="{ critical: a.level === 'critical' }">
              <div class="ms-todo-body">
                <p class="ms-todo-title">{{ metricLabel(a.metric) }} {{ num(a.value) }} · {{ a.device_code }}</p>
                <p class="ms-todo-msg">{{ a.message }}</p>
                <p class="ms-todo-time mono">{{ shortTs(a.created_at) }}</p>
              </div>
              <button class="ms-ack" type="button" :disabled="acking[a.id]" @click="ack(a.id)">
                {{ acking[a.id] ? '确认中…' : '一键确认' }}
              </button>
            </li>
          </ul>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ackAlert, aiChat, getAlerts, getDevices, getMeta, getLatest } from '../api'
import { ALERT_LIMIT, POLL_INTERVAL_MS } from '../config'
import { metricLabel as labelOf, metricUnit } from '../metrics'
import { chatTag } from '../sourceLabel'
import { navigate } from '../router'

const go = (p) => navigate(p)

const meta = ref({})
const devices = ref([])
const latest = ref([])
const todos = ref([])
const metaLoading = ref(false)
const todosLoading = ref(false)
const errors = ref([])
const acking = reactive({})

const diseaseMsg = ref(null)
const diseaseLoading = ref(false)
const diseaseError = ref('')

const clock = ref('')
const batteryPct = ref('--')

let timer = null
let clockTimer = null

const sessionId = `mob-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`

// 指标中文名与单位统一取自 metrics.js 注册表，C 区 co2 也有中文名
const metricLabel = (m) => labelOf(m)
const num = (v) => (v === null || v === undefined ? '--' : Number(v).toFixed(1))

function shortTs(ts) {
  const s = String(ts || '')
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : '--'
}

function pushError(msg) {
  if (!msg) return
  if (!errors.value.includes(msg)) errors.value = [...errors.value, msg].slice(-3)
}

const diseaseTag = computed(() => chatTag(diseaseMsg.value || {}))

// 地块卡片：plots（/api/meta）+ devices（/api/devices）+ 最新遥测（/api/telemetry/latest）
const plotCards = computed(() => {
  return (meta.value?.plots || []).map((p) => {
    const mine = devices.value.filter((d) => d.plot_code === p.plot_code)
    // 该地块的全部最新遥测（多台设备）：逐指标取第一个非空值
    const rows = latest.value.filter((l) => l.plot_code === p.plot_code)
    const first = rows[0] || {}
    const pick = (m) => {
      const hit = rows.find((r) => r[m] !== null && r[m] !== undefined)
      return hit ? hit[m] : null
    }
    // 该地块生效指标：优先 /api/meta 的 metrics，缺失时按已有数据兜底
    const declared = Array.isArray(p.metrics) && p.metrics.length ? p.metrics : ['temperature', 'humidity']
    const row = {
      plot_code: p.plot_code,
      name: p.name || p.plot_name,
      crop: p.crop || '--',
      metrics: declared,
      devices: mine.length,
      online: mine.filter((d) => d.status === 'online').length,
      ts: first.ts,
      battery: first.battery
    }
    for (const m of declared) row[m] = pick(m)
    return row
  })
})

async function loadMeta() {
  metaLoading.value = true
  try {
    meta.value = await getMeta()
  } catch (err) {
    pushError(`元数据加载失败：${err.message}`)
  } finally {
    metaLoading.value = false
  }
}

async function loadDevices() {
  try {
    const res = await getDevices()
    devices.value = Array.isArray(res?.items) ? res.items : []
  } catch (err) {
    pushError(`设备列表加载失败：${err.message}`)
  }
}

async function loadLatest() {
  try {
    const res = await getLatest()
    latest.value = Array.isArray(res?.items) ? res.items : []
    const first = latest.value.find((i) => i.battery != null)
    batteryPct.value = first ? `${Math.round(Number(first.battery))}%` : '--'
  } catch (err) {
    pushError(`最新遥测加载失败：${err.message}`)
  }
}

async function loadTodos() {
  todosLoading.value = true
  try {
    const res = await getAlerts(ALERT_LIMIT, true)
    todos.value = Array.isArray(res?.items) ? res.items : []
  } catch (err) {
    pushError(`待办任务加载失败：${err.message}`)
  } finally {
    todosLoading.value = false
  }
}

async function ack(id) {
  acking[id] = true
  try {
    await ackAlert(id)
    await loadTodos()
  } catch (err) {
    pushError(`确认失败：${err.message}`)
  } finally {
    acking[id] = false
  }
}

// 拍照识病：走真实 POST /api/ai/chat，无 Key 时后端回落 Mock 并置 degraded=true
async function askDisease() {
  diseaseLoading.value = true
  diseaseError.value = ''
  const question = '我拍到柑橘叶片有黄化斑点，请判断病害并给防治方案'
  try {
    const res = await aiChat(question, sessionId, undefined)
    diseaseMsg.value = { ...res, question }
    if (res?.error) diseaseError.value = `AI 服务降级：${res.error}`
  } catch (err) {
    diseaseError.value = `识病请求失败：${err.message}`
  } finally {
    diseaseLoading.value = false
  }
}

function tickClock() {
  clock.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

onMounted(async () => {
  tickClock()
  clockTimer = setInterval(tickClock, 30000)
  await loadMeta()
  await Promise.allSettled([loadDevices(), loadLatest(), loadTodos()])
  timer = setInterval(() => {
    loadDevices()
    loadLatest()
    loadTodos()
  }, POLL_INTERVAL_MS)
})

onBeforeUnmount(() => {
  if (timer) { clearInterval(timer); timer = null }
  if (clockTimer) { clearInterval(clockTimer); clockTimer = null }
})
</script>

<style scoped>
.ms-wrap { min-height: 100%; display: flex; align-items: flex-start; justify-content: center; padding: 22px 14px 34px; }

/* 手机外壳：圆角 + 刘海 + 状态条 */
.ms-phone {
  position: relative;
  width: 100%; max-width: 400px;
  background: #0b0b0b;
  border: 2px solid rgba(255, 255, 255, 0.14);
  border-radius: 34px;
  padding: 14px 10px 16px;
  box-shadow: 0 18px 46px rgba(0, 0, 0, 0.6);
}
.ms-notch {
  position: absolute; top: 7px; left: 50%; transform: translateX(-50%);
  width: 104px; height: 16px; border-radius: 9px; background: #000;
  border: 1px solid rgba(255, 255, 255, 0.09);
}
.ms-statusbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 4px 16px 8px; font-size: 10px; color: var(--v2-sub);
}
.ms-sig { display: inline-flex; align-items: center; gap: 3px; }
.ms-bar { width: 3px; height: 7px; background: var(--v2-sub); border-radius: 1px; display: inline-block; }
.ms-bar:nth-child(2) { height: 9px; }
.ms-bar:nth-child(3) { height: 11px; background: var(--v2-cyan); }
.ms-batt { font-style: normal; margin-left: 5px; color: var(--v2-text); }

.ms-screen {
  background: var(--v2-bg);
  border: 1px solid var(--v2-line-soft);
  border-radius: 22px;
  padding: 12px 12px 16px;
  display: flex; flex-direction: column; gap: 12px;
  max-height: 78vh; overflow-y: auto;
}

.ms-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.ms-title h1 { margin: 0; font-size: 14px; color: var(--v2-text); letter-spacing: 0.06em; }
.ms-sub { margin: 2px 0 0; font-size: 10px; color: var(--v2-sub); }
.ms-back {
  font-family: inherit; font-size: 11px; cursor: pointer; flex: 0 0 auto;
  color: var(--v2-cyan); background: rgba(0, 229, 255, 0.08);
  border: 1px solid var(--v2-line-color); border-radius: 20px; padding: 5px 11px;
}
.ms-back:hover { background: rgba(0, 229, 255, 0.16); }

.ms-err { margin: 0; font-size: 10.5px; color: var(--v2-red); border-left: 2px solid var(--v2-red); padding: 3px 8px; background: rgba(255, 59, 48, 0.08); }

.ms-card { background: var(--v2-panel); border: var(--v2-line); border-radius: 10px; padding: 10px 11px; }
.ms-card-title { display: flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 600; color: var(--v2-text); margin-bottom: 9px; }
.ms-card-title .sub { font-size: 10px; font-weight: 400; color: var(--v2-sub); }

.ms-shot { border-radius: 8px; overflow: hidden; margin-bottom: 9px; }
.ms-shot-ph {
  height: 108px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 5px;
  background: repeating-linear-gradient(45deg, rgba(255,255,255,0.03) 0 8px, rgba(255,255,255,0.06) 8px 16px);
  border: 1px dashed rgba(255, 255, 255, 0.16); border-radius: 8px;
}
.ms-shot-icon { font-size: 30px; }
.ms-shot-tip { font-size: 10px; color: var(--v2-sub); }

.ms-cta {
  width: 100%; font-family: inherit; font-size: 13.5px; font-weight: 700; cursor: pointer;
  color: #06110a; background: var(--v2-cyan); border: 0; border-radius: 9px; padding: 12px;
}
.ms-cta:disabled { opacity: 0.6; cursor: default; }

.ms-bubble { margin-top: 10px; border-left: 2px solid var(--v2-green); background: rgba(0, 230, 118, 0.06); border-radius: 0 8px 8px 0; padding: 8px 10px; }
.ms-bubble-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ms-meta { font-size: 10px; color: var(--v2-sub); }
.ms-q { margin: 7px 0 5px; font-size: 11px; color: var(--v2-sub); }
.ms-a { margin: 0; font-size: 12px; line-height: 1.7; color: var(--v2-text); white-space: pre-wrap; }

.ms-plots { display: flex; flex-direction: column; gap: 9px; }
.ms-plot { border: 1px solid var(--v2-line-soft); border-radius: 8px; padding: 8px 9px; background: rgba(0, 0, 0, 0.18); }
.ms-plot-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.ms-plot-head b { font-size: 12px; color: var(--v2-cyan); }
.ms-plot-code { font-size: 9.5px; color: var(--v2-sub); }
.ms-metrics { display: flex; flex-wrap: wrap; gap: 3px 11px; margin-top: 6px; }
.ms-metric { display: inline-flex; align-items: baseline; gap: 4px; font-size: 11px; }
.ms-metric i { font-style: normal; font-size: 9.5px; color: var(--v2-sub); }
.ms-metric b { color: var(--v2-text); }
.ms-plot-foot { margin: 6px 0 0; font-size: 9.5px; color: var(--v2-sub); }

.ms-todos { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.ms-todo {
  display: flex; align-items: center; gap: 9px;
  border-left: 3px solid var(--v2-warn); border-radius: 0 8px 8px 0;
  background: rgba(255, 179, 0, 0.07); padding: 8px 9px;
}
.ms-todo.critical { border-left-color: var(--v2-red); background: rgba(255, 59, 48, 0.1); }
.ms-todo-body { flex: 1; min-width: 0; }
.ms-todo-title { margin: 0; font-size: 11.5px; font-weight: 600; color: var(--v2-text); }
.ms-todo-msg { margin: 2px 0; font-size: 10.5px; color: var(--v2-sub); }
.ms-todo-time { margin: 0; font-size: 9.5px; color: var(--v2-sub); }
.ms-ack {
  flex: 0 0 auto; font-family: inherit; font-size: 10.5px; font-weight: 600; cursor: pointer;
  color: #06110a; background: var(--v2-green); border: 0; border-radius: 6px; padding: 7px 10px;
}
.ms-ack:disabled { opacity: 0.6; cursor: default; }

.ms-skeleton { height: 56px; border-radius: 8px; background: rgba(255, 255, 255, 0.05); }
.ms-empty { font-size: 11px; color: var(--v2-sub); padding: 6px 0; }

@media (max-width: 420px) {
  .ms-phone { border-radius: 26px; padding: 12px 8px 14px; }
  .ms-screen { max-height: none; }
}
</style>
