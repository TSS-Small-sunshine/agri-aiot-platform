<template>
  <div class="screen">
    <!-- 顶部错误条：任何请求失败都必须在 UI 上可见 -->
    <transition name="fade">
      <div v-if="errors.length" class="error-bar">
        <i class="dot offline"></i>
        <span class="etitle">接口异常（{{ errors.length }}）：</span>
        <span class="elist">{{ errors.join(' ｜ ') }}</span>
        <button class="btn danger" @click="refreshAll">立即重试</button>
        <button class="btn" @click="errors = []">忽略</button>
      </div>
    </transition>

    <header class="topbar panel">
      <div class="brand">
        <i class="logo"></i>
        <div class="titles">
          <h1>智慧农业 AIoT 数据大屏</h1>
          <p class="sub">福建省南平市 · 柑橘示范园实时监测</p>
        </div>
      </div>
      <div class="kpis">
        <div class="kpi">
          <span class="k-label">在线设备</span>
          <span class="k-value mono">{{ onlineCount }}<em>/{{ devices.length }}</em></span>
        </div>
        <div class="kpi">
          <span class="k-label">平均温度</span>
          <span class="k-value mono temp">{{ f1(summary?.temperature?.avg) }}<em>℃</em></span>
        </div>
        <div class="kpi">
          <span class="k-label">平均湿度</span>
          <span class="k-value mono humi">{{ f1(summary?.humidity?.avg) }}<em>%</em></span>
        </div>
        <div class="kpi">
          <span class="k-label">平均墒情</span>
          <span class="k-value mono soil">{{ f1(summary?.soil_moisture?.avg) }}<em>%</em></span>
        </div>
        <div class="kpi">
          <span class="k-label">未确认告警</span>
          <span class="k-value mono" :class="{ danger: unackedCount > 0 }">{{ unackedCount }}<em>条</em></span>
        </div>
      </div>
      <div class="status">
        <span class="pill" :class="health?.status === 'ok' ? 'ok' : 'bad'">
          <i class="dot" :class="health?.status === 'ok' ? 'online' : 'offline'"></i>
          后端 {{ health?.status === 'ok' ? '正常' : '不可达' }}
        </span>
        <span class="pill" :class="health?.mqtt?.connected ? 'ok' : 'bad'">
          <i class="dot" :class="health?.mqtt?.connected ? 'online' : 'offline'"></i>
          MQTT {{ health?.mqtt?.connected ? '已连接' : '断开' }}
        </span>
        <span class="pill" :class="health?.llm?.configured ? 'ok' : 'warn'">
          LLM {{ health?.llm?.configured ? '已配置' : 'Mock 降级' }}
        </span>
        <span class="pill mono">v{{ health?.version || '--' }}</span>
        <span class="pill mono">{{ nowText }}</span>
      </div>
    </header>

    <main class="grid">
      <section class="cell chart">
        <RealtimeChart :devices="devices" />
      </section>
      <section class="cell devices">
        <DeviceStatusCard
          :devices="devices" :loading="loading.devices" :error="localErr.devices"
          :focus-device="focusDevice" @focus="focusDevice = $event"
        />
      </section>
      <section class="cell gauge">
        <SoilGauge
          :value="focusSoil" :device-code="focusDevice" :thresholds="thresholds.soil_moisture"
          :error="localErr.devices"
        />
      </section>
      <section class="cell alerts">
        <AlertPanel :alerts="alerts" :loading="loading.alerts" :error="localErr.alerts" @ack="ack" />
      </section>
      <section class="cell plotmap">
        <PlotMap :devices="devices" :meta="meta" :focus-device="focusDevice" :error="localErr.meta"
                 @focus="focusDevice = $event" />
      </section>
      <section class="cell aichat">
        <AiChat @error="pushError" />
      </section>
    </main>

    <footer class="footer">
      <span>轮询间隔 {{ POLL_INTERVAL_MS / 1000 }}s</span>
      <span>数据源 /api · 阈值来自 /api/meta</span>
      <span class="mono">{{ lastTick || '尚未同步' }}</span>
    </footer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import RealtimeChart from './components/RealtimeChart.vue'
import DeviceStatusCard from './components/DeviceStatusCard.vue'
import SoilGauge from './components/SoilGauge.vue'
import AlertPanel from './components/AlertPanel.vue'
import PlotMap from './components/PlotMap.vue'
import AiChat from './components/AiChat.vue'
import { ackAlert, getAlerts, getDevices, getHealth, getMeta, getSummary } from './api'
import { ALERT_LIMIT, POLL_INTERVAL_MS, SUMMARY_HOURS } from './config'

const health = ref(null)
const devices = ref([])
const alerts = ref([])
const meta = ref({})
const summary = ref(null)
const focusDevice = ref('')
const errors = ref([])
const lastTick = ref('')
const nowText = ref(new Date().toLocaleTimeString('zh-CN', { hour12: false }))
const loading = reactive({ devices: false, alerts: false })
const localErr = reactive({ devices: '', alerts: '', meta: '' })

let timer = null
let clock = null

const f1 = (v) => (v === null || v === undefined ? '--' : Number(v).toFixed(1))
const onlineCount = computed(() => devices.value.filter((d) => d.status === 'online').length)
const unackedCount = computed(() => alerts.value.filter((a) => !a.acked).length)
const thresholds = computed(() => meta.value?.thresholds || {})

// 墒情仪表：优先聚焦设备自身墒情，其次该地块墒情站，最后全局平均
const focusSoil = computed(() => {
  const pick = (code) => devices.value.find((d) => d.device_code === code)?.latest?.soil_moisture
  const direct = pick(focusDevice.value)
  if (direct !== null && direct !== undefined) return Number(direct)
  const focused = devices.value.find((d) => d.device_code === focusDevice.value)
  if (focused) {
    const peer = devices.value.find((d) => d.plot_code === focused.plot_code && d.type === 'soil')
    if (peer?.latest?.soil_moisture !== null && peer?.latest?.soil_moisture !== undefined) {
      return Number(peer.latest.soil_moisture)
    }
  }
  const avg = summary.value?.soil_moisture?.avg
  return avg === null || avg === undefined ? null : Number(avg)
})

function pushError(msg) {
  if (!msg) return
  if (!errors.value.includes(msg)) errors.value = [...errors.value, msg].slice(-4)
}
function clearError(msg) {
  errors.value = errors.value.filter((e) => e !== msg)
}

async function loadHealth() {
  try {
    health.value = await getHealth()
    clearError(lastHealthErr)
  } catch (err) {
    lastHealthErr = `健康检查失败：${err.message}`
    pushError(lastHealthErr)
  }
}
let lastHealthErr = ''

async function loadDevices() {
  loading.devices = true
  try {
    const res = await getDevices()
    devices.value = Array.isArray(res?.items) ? res.items : []
    localErr.devices = ''
    clearError(lastDevErr)
    if (!focusDevice.value && devices.value.length) focusDevice.value = devices.value[0].device_code
  } catch (err) {
    lastDevErr = `设备列表加载失败：${err.message}`
    localErr.devices = lastDevErr
    pushError(lastDevErr)
  } finally {
    loading.devices = false
  }
}
let lastDevErr = ''

async function loadAlerts() {
  loading.alerts = true
  try {
    const res = await getAlerts(ALERT_LIMIT, false)
    alerts.value = Array.isArray(res?.items) ? res.items : []
    localErr.alerts = ''
    clearError(lastAlertErr)
  } catch (err) {
    lastAlertErr = `告警列表加载失败：${err.message}`
    localErr.alerts = lastAlertErr
    pushError(lastAlertErr)
  } finally {
    loading.alerts = false
  }
}
let lastAlertErr = ''

async function loadMeta() {
  try {
    meta.value = await getMeta()
    localErr.meta = ''
    clearError(lastMetaErr)
  } catch (err) {
    lastMetaErr = `元数据加载失败：${err.message}`
    localErr.meta = lastMetaErr
    pushError(lastMetaErr)
  }
}
let lastMetaErr = ''

async function loadSummary() {
  try {
    summary.value = await getSummary(SUMMARY_HOURS)
    clearError(lastSumErr)
  } catch (err) {
    lastSumErr = `统计摘要加载失败：${err.message}`
    pushError(lastSumErr)
  }
}
let lastSumErr = ''

async function ack(id) {
  try {
    await ackAlert(id)
    await loadAlerts()
  } catch (err) {
    const msg = `告警确认失败：${err.message}`
    localErr.alerts = msg
    pushError(msg)
  }
}

// 不在此处清空 errors：每个 loader 成功时各自 clearError，
// 否则重试瞬间错误条会闪一下再重新出现
async function refreshAll() {
  await Promise.allSettled([loadHealth(), loadDevices(), loadAlerts(), loadMeta(), loadSummary()])
  lastTick.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
}

onMounted(async () => {
  await loadMeta() // 阈值先就绪，仪表盘才有正确的分档
  await refreshAll()
  timer = setInterval(() => {
    loadHealth()
    loadDevices()
    loadAlerts()
    loadSummary()
  }, POLL_INTERVAL_MS)
  clock = setInterval(() => {
    nowText.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  }, 1000)
})

onBeforeUnmount(() => {
  if (timer) { clearInterval(timer); timer = null }
  if (clock) { clearInterval(clock); clock = null }
})
</script>

<style scoped>
.screen {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  padding: var(--gap);
  max-width: 2200px;
  margin: 0 auto;
}

.error-bar {
  display: flex; align-items: center; gap: 10px;
  background: var(--red-soft);
  border: 1px solid rgba(244, 63, 94, 0.6);
  border-radius: var(--radius);
  padding: 8px 12px;
  box-shadow: var(--glow-red);
  font-size: 12.5px;
}
.error-bar .etitle { color: var(--red); font-weight: 600; white-space: nowrap; }
.error-bar .elist { color: #ffd7de; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.topbar { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; padding: 10px 16px; }
.brand { display: flex; align-items: center; gap: 12px; min-width: 300px; }
.logo {
  width: 34px; height: 34px; border-radius: 9px; flex: 0 0 auto;
  background: linear-gradient(135deg, var(--cyan), var(--green));
  box-shadow: var(--glow-cyan);
  position: relative;
}
.logo::after {
  content: ''; position: absolute; inset: 9px;
  border-radius: 4px; background: rgba(10, 16, 32, 0.85);
}
.titles h1 {
  margin: 0; font-size: 17px; letter-spacing: 0.1em;
  background: linear-gradient(90deg, #e2f2ff, var(--cyan) 60%, var(--green));
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.titles .sub { margin: 1px 0 0; font-size: 11px; color: var(--text-faint); letter-spacing: 0.06em; }

.kpis { display: flex; gap: 10px; flex-wrap: wrap; flex: 1; }
.kpi {
  background: rgba(9, 17, 31, 0.6);
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  padding: 5px 12px;
  min-width: 104px;
}
.k-label { display: block; font-size: 10.5px; color: var(--text-faint); letter-spacing: 0.05em; }
.k-value { font-size: 20px; font-weight: 700; color: var(--text-main); line-height: 1.25; }
.k-value em { font-size: 11px; font-style: normal; color: var(--text-faint); margin-left: 2px; }
.k-value.temp { color: #fbbf24; }
.k-value.humi { color: var(--cyan); }
.k-value.soil { color: var(--green); }
.k-value.danger { color: var(--red); text-shadow: var(--glow-red); }

.status { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pill {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11px; color: var(--text-sub);
  border: 1px solid var(--line-soft); border-radius: 20px; padding: 3px 10px;
  background: rgba(9, 17, 31, 0.5);
}
.pill.ok { color: var(--green); border-color: rgba(52, 211, 153, 0.45); }
.pill.bad { color: var(--red); border-color: rgba(244, 63, 94, 0.5); }
.pill.warn { color: #fbbf24; border-color: rgba(251, 191, 36, 0.45); }

.grid {
  flex: 1;
  display: grid;
  gap: var(--gap);
  grid-template-columns: repeat(12, minmax(0, 1fr));
  grid-auto-rows: minmax(220px, auto);
}
.cell { min-width: 0; display: flex; }
.cell > * { flex: 1; }
.chart { grid-column: span 8; grid-row: span 2; }
.devices { grid-column: span 4; grid-row: span 2; }
.gauge { grid-column: span 4; }
.alerts { grid-column: span 4; }
.plotmap { grid-column: span 4; }
.aichat { grid-column: span 12; min-height: 320px; }

.footer {
  display: flex; align-items: center; gap: 18px; flex-wrap: wrap;
  font-size: 11px; color: var(--text-faint); padding: 0 4px 4px;
}

.fade-enter-active, .fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

@media (max-width: 1400px) {
  .chart { grid-column: span 12; }
  .devices { grid-column: span 12; }
  .gauge, .alerts, .plotmap { grid-column: span 6; }
}
@media (max-width: 900px) {
  .gauge, .alerts, .plotmap { grid-column: span 12; }
}
</style>
