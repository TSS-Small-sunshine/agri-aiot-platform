<template>
  <div class="mv">
    <!-- 顶栏 -->
    <header class="mv-top panel">
      <div class="brand">
        <i class="logo"></i>
        <div class="titles">
          <h1>智慧农业 AIoT 决策中枢</h1>
          <p class="sub">福建省南平市 · 柑橘示范园 · 可推演 / 可执行 / 可溯源</p>
        </div>
      </div>

      <div class="kpis">
        <div class="kpi">
          <span class="k-label">在线设备</span>
          <span class="k-value mono">{{ onlineCount }}<em>/{{ devices.length }}</em></span>
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
        <span class="pill warn" :title="'当前模型'">
          模型 <b class="mono model-name">{{ modelName }}</b>
        </span>

        <label class="switch" title="大字模式：隐藏复杂面板，只保留最高优先级告警与干预建议">
          <input type="checkbox" v-model="bigFont" @change="onBigFont(bigFont)" />
          <span class="track"><span class="knob"></span></span>
          <span class="sw-label">大字模式</span>
        </label>

        <button class="btn gear" type="button" title="模型与接口设置" @click="settingsOpen = true">
          <span class="gear-icon">⚙</span> 设置
        </button>
      </div>
    </header>

    <p v-if="errors.length" class="err-inline mv-err">接口异常：{{ errors.join(' ｜ ') }}</p>

    <!-- 大字模式：全屏重排的超大号卡片视图。
         这里刻意用 v-if 而不是 v-show —— 大字模式要「隐藏复杂面板」，
         但推演树画布必须活下来（见 .mv-body 的 v-show 说明），
         所以真正承载 ECharts 的 .mv-body 用 v-show 隐藏而非卸载。 -->
    <AccessiblePanel
      v-if="bigFont"
      :alerts="alerts"
      :reasoning="reasoning"
      :devices="devices"
      class="mv-accessible"
      @close="onBigFont(false)"
    />

    <!-- 主体：左 2.5D 地块 / 中 因果树 / 下 AI 双轨对话
         大字模式用 v-show 而非 v-if：ReasoningTree 的 .rt-chart 一旦被卸载，
         ECharts 实例会失去宿主 DOM；虽然 render() 有重建逻辑，
         但 props.result 未变时 watch 不触发，重建时机不可靠。
         display:none 让容器仍在文档流中，关闭大字模式后 chart 直接可见且尺寸不变。 -->
    <main v-show="!bigFont" class="mv-grid mv-body">
      <section class="cell left">
        <PlotGrid25D
          :plots="plots"
          :devices="devices"
          :selected="selectedPlot"
          :loading="metaLoading"
          :error="metaError"
          :levels="plotLevels"
          @select="onSelectPlot"
        />
        <div class="panel weather">
          <div class="panel-title">
            <span class="t-left"><span class="bar"></span>园区气象</span>
            <span class="sub">{{ weatherSource || '--' }}</span>
          </div>
          <div v-if="weatherError" class="err-inline">{{ weatherError }}</div>
          <div v-else-if="!weather" class="empty">暂无气象数据</div>
          <div v-else class="w-grid">
            <span class="w-item"><i>温度</i><b class="mono">{{ num(weather.temperature) }}℃</b></span>
            <span class="w-item"><i>湿度</i><b class="mono">{{ num(weather.humidity) }}%</b></span>
            <span class="w-item"><i>降雨</i><b class="mono">{{ num(weather.rainfall_mm) }}mm</b></span>
            <span class="w-item"><i>风力</i><b class="mono">{{ weather.wind_level ?? '--' }} 级</b></span>
            <span class="w-item"><i>天气</i><b class="mono nowrap">{{ weather.condition || '--' }}</b></span>
            <span class="w-item"><i>风向</i><b class="mono">{{ weather.wind_dir || '--' }}</b></span>
          </div>
        </div>
      </section>

      <section class="cell center">
        <ReasoningTree
          :result="reasoning"
          :loading="reasoningLoading"
          :error="reasoningError"
          @rerun="runReasoning(selectedPlot)"
          @executed="onCommandExecuted"
        />
      </section>

      <section class="cell bottom">
        <AiChat ref="aiRef" @error="pushError" />
      </section>
    </main>

    <footer v-show="!bigFont" class="footer">
      <span>轮询间隔 {{ POLL_INTERVAL_MS / 1000 }}s</span>
      <span>推演 POST /api/reasoning/simulate · 指令 POST /api/command/execute</span>
      <span class="mono">{{ lastTick || '尚未同步' }}</span>
      <span class="mono">当前地块 {{ selectedPlot || '--' }}</span>
    </footer>

    <SettingsModal :open="settingsOpen" @close="settingsOpen = false" @saved="onSaved" />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import AccessiblePanel from '../components/AccessiblePanel.vue'
import AiChat from '../components/AiChat.vue'
import PlotGrid25D from '../components/PlotGrid25D.vue'
import ReasoningTree from '../components/ReasoningTree.vue'
import SettingsModal from '../components/SettingsModal.vue'
import { getAlerts, getConfig, getDevices, getHealth, getMeta, getSummary, getWeatherLatest, reasoningSimulate } from '../api'
import { ALERT_LIMIT, POLL_INTERVAL_MS, SUMMARY_HOURS } from '../config'
import { pushToast } from '../toast'

const health = ref(null)
const devices = ref([])
const alerts = ref([])
const meta = ref({})
const summary = ref(null)
const weather = ref(null)
const weatherSource = ref('')
const weatherError = ref('')
const reasoning = ref(null)
const reasoningLoading = ref(false)
const reasoningError = ref('')
const selectedPlot = ref('')
const modelName = ref('--')
const errors = ref([])
const lastTick = ref('')
const metaLoading = ref(false)
const metaError = ref('')
const settingsOpen = ref(false)
const bigFont = ref(false)
const aiRef = ref(null)

let timer = null

const plots = computed(() => meta.value?.plots || [])
const f1 = (v) => (v === null || v === undefined ? '--' : Number(v).toFixed(1))
const num = (v) => (v === null || v === undefined ? '--' : Number(v).toFixed(1))
const onlineCount = computed(() => devices.value.filter((d) => d.status === 'online').length)
const unackedCount = computed(() => alerts.value.filter((a) => !a.acked).length)

// 地块着色：该地块有未确认 critical 告警 → high；有未确认告警 → warn；否则 good
const plotLevels = computed(() => {
  const out = {}
  for (const p of plots.value) {
    const codes = (p.devices || [])
    const mine = alerts.value.filter((a) => !a.acked && codes.includes(a.device_code))
    if (mine.some((a) => a.level === 'critical')) out[p.plot_code] = 'high'
    else if (mine.length) out[p.plot_code] = 'warn'
    else out[p.plot_code] = 'good'
  }
  return out
})

function pushError(msg) {
  if (!msg) return
  if (!errors.value.includes(msg)) errors.value = [...errors.value, msg].slice(-4)
}

async function loadMeta() {
  metaLoading.value = true
  try {
    meta.value = await getMeta()
    metaError.value = ''
    if (!selectedPlot.value && plots.value.length) selectedPlot.value = plots.value[0].plot_code
  } catch (err) {
    metaError.value = `元数据加载失败：${err.message}`
    pushError(metaError.value)
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

async function loadAlerts() {
  try {
    const res = await getAlerts(ALERT_LIMIT, false)
    alerts.value = Array.isArray(res?.items) ? res.items : []
  } catch (err) {
    pushError(`告警列表加载失败：${err.message}`)
  }
}

async function loadHealth() {
  try {
    health.value = await getHealth()
  } catch (err) {
    pushError(`健康检查失败：${err.message}`)
  }
}

async function loadSummary() {
  try {
    summary.value = await getSummary(SUMMARY_HOURS)
  } catch (err) {
    pushError(`统计摘要加载失败：${err.message}`)
  }
}

async function loadWeather(code) {
  if (!code) return
  try {
    const res = await getWeatherLatest(code)
    weather.value = res?.latest || null
    weatherSource.value = res?.source ? `来源 ${res.source}` : ''
    weatherError.value = ''
  } catch (err) {
    weather.value = null
    weatherError.value = `气象数据加载失败：${err.message}`
  }
}

async function loadModelName() {
  try {
    const c = await getConfig()
    modelName.value = c?.model || '（默认）'
  } catch {
    modelName.value = '--'
  }
}

async function onSelectPlot(plot) {
  selectedPlot.value = plot.plot_code
  loadWeather(plot.plot_code)
  await runReasoning(plot.plot_code)
}

async function runReasoning(code) {
  if (!code || reasoningLoading.value) return
  reasoningLoading.value = true
  reasoningError.value = ''
  try {
    const res = await reasoningSimulate(code, null)
    reasoning.value = res
    // 双轨对话的第二轨：推演结果进入对话流（含白盒步骤）
    aiRef.value?.pushReasoning(res)
  } catch (err) {
    reasoningError.value = `推演失败：${err.message}`
    pushError(reasoningError.value)
  } finally {
    reasoningLoading.value = false
  }
}

// 指令下发只更新对话流里那条推演记录的状态，不重新推演（重新推演会打断闭环观察）
function onCommandExecuted({ node, res }) {
  aiRef.value?.updateReasoningCommand?.(node?.id, res)
}

// 大字模式：可逆切换。开启时桌面复杂面板整体 display:none（不卸载 DOM），
// 关闭时原样恢复；推演树实例因此始终存活，不会重现「canvas 永久空白」。
function onBigFont(next) {
  const on = typeof next === 'boolean' ? next : !!bigFont.value
  bigFont.value = on
  pushToast(on ? '已进入大字模式：仅显示最高优先级告警与干预建议' : '已退出大字模式，全部面板已恢复', { kind: on ? 'warn' : 'ok' })
}

function onSaved(cfg) {
  modelName.value = cfg?.model || '（默认）'
  pushToast(`配置已保存 · 当前模型 ${modelName.value}`, { kind: 'ok' })
}

async function refreshAll() {
  await Promise.allSettled([loadHealth(), loadDevices(), loadAlerts(), loadSummary(), loadModelName()])
  if (selectedPlot.value) loadWeather(selectedPlot.value)
  lastTick.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
}

onMounted(async () => {
  await loadMeta()
  await refreshAll()
  timer = setInterval(() => {
    loadHealth()
    loadDevices()
    loadAlerts()
    loadSummary()
  }, POLL_INTERVAL_MS)
})

onBeforeUnmount(() => {
  if (timer) { clearInterval(timer); timer = null }
})
</script>

<style scoped>
.mv-accessible { flex: 1; }

.mv { min-height: 100%; display: flex; flex-direction: column; gap: var(--v2-gap); padding: var(--v2-gap); max-width: 2200px; margin: 0 auto; }

.mv-top { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; padding: 9px 14px; }
.brand { display: flex; align-items: center; gap: 11px; min-width: 290px; }
.logo {
  width: 32px; height: 32px; border-radius: 7px; flex: 0 0 auto;
  background: var(--v2-cyan); box-shadow: 0 0 14px rgba(0, 229, 255, 0.45);
  position: relative;
}
.logo::after { content: ''; position: absolute; inset: 9px; background: var(--v2-bg); border-radius: 3px; }
.titles h1 { margin: 0; font-size: 16px; letter-spacing: 0.1em; color: var(--v2-text); }
.titles .sub { margin: 1px 0 0; font-size: 10.5px; color: var(--v2-sub); letter-spacing: 0.05em; }

.kpis { display: flex; gap: 9px; flex-wrap: wrap; flex: 1; }
.kpi { background: rgba(255, 255, 255, 0.03); border: var(--v2-line); border-radius: var(--v2-r-sm); padding: 4px 11px; min-width: 100px; }
.k-label { display: block; font-size: 10px; color: var(--v2-sub); letter-spacing: 0.05em; }
.k-value { font-size: 19px; font-weight: 700; color: var(--v2-text); line-height: 1.25; }
.k-value em { font-size: 10.5px; font-style: normal; color: var(--v2-sub); margin-left: 2px; }
.k-value.soil { color: var(--v2-green); }
.k-value.danger { color: var(--v2-red); }

.status { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.pill {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11px; color: var(--v2-sub);
  border: var(--v2-line); border-radius: 20px; padding: 3px 10px;
}
.pill.ok { color: var(--v2-green); border-color: rgba(0, 230, 118, 0.45); }
.pill.bad { color: var(--v2-red); border-color: rgba(255, 59, 48, 0.5); }
.pill.warn { color: var(--v2-warn); border-color: rgba(255, 179, 0, 0.45); }
.model-name { color: var(--v2-cyan); font-weight: 600; max-width: 190px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.switch { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; font-size: 11px; color: var(--v2-sub); }
.switch input { position: absolute; opacity: 0; width: 0; height: 0; }
.track {
  width: 30px; height: 16px; border-radius: 10px;
  background: rgba(255, 255, 255, 0.1);
  border: var(--v2-line);
  position: relative; transition: background 0.18s;
}
.knob {
  position: absolute; top: 1px; left: 1px; width: 12px; height: 12px; border-radius: 50%;
  background: var(--v2-sub); transition: transform 0.18s, background 0.18s;
}
.switch input:checked + .track { background: rgba(0, 229, 255, 0.25); }
.switch input:checked + .track .knob { transform: translateX(14px); background: var(--v2-cyan); }
.gear { display: inline-flex; align-items: center; gap: 4px; }
.gear-icon { font-size: 12px; }

.mv-err { margin: 0; }

.mv-grid {
  flex: 1;
  display: grid;
  gap: var(--v2-gap);
  grid-template-columns: minmax(300px, 360px) minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr) minmax(280px, auto);
  grid-template-areas:
    'left center'
    'bottom bottom';
}
.cell { min-width: 0; display: flex; flex-direction: column; gap: var(--v2-gap); }
.left { grid-area: left; }
.center { grid-area: center; }
.bottom { grid-area: bottom; }
.bottom > * { flex: 1; }

.weather { padding: 8px 11px; }
.w-grid { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 11px; }
.w-item { display: inline-flex; align-items: baseline; gap: 5px; }
.w-item i { font-style: normal; color: var(--v2-sub); font-size: 10.5px; }
.w-item b { color: var(--v2-text); max-width: 110px; }

.footer { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; font-size: 10.5px; color: var(--v2-sub); padding: 0 3px 3px; }

@media (max-width: 1200px) {
  .mv-grid { grid-template-columns: minmax(0, 1fr); grid-template-areas: 'left' 'center' 'bottom'; }
}
</style>
