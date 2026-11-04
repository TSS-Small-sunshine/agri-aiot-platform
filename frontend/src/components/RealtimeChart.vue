<template>
  <section class="panel realtime">
    <header class="panel-title">
      <span class="t-left"><i class="bar"></i>实时温湿度趋势</span>
      <span class="sub mono">{{ windowLabel }}</span>
    </header>

    <div class="controls">
      <label class="ctl">
        <span>设备</span>
        <select v-model="deviceCode" :disabled="!devices.length">
          <option v-if="!devices.length" value="">暂无设备</option>
          <option v-for="d in devices" :key="d.device_code" :value="d.device_code">
            {{ d.name }}（{{ d.device_code }}）
          </option>
        </select>
      </label>
      <label class="ctl">
        <span>时间窗</span>
        <select v-model.number="hours">
          <option :value="1">近 1 小时</option>
          <option :value="6">近 6 小时</option>
          <option :value="24">近 24 小时</option>
        </select>
      </label>
      <button class="btn" :disabled="loading" @click="reload">
        {{ loading ? '加载中…' : '刷新' }}
      </button>
    </div>

    <p v-if="error" class="err-inline">{{ error }}</p>

    <div class="chart-box">
      <div ref="chartEl" class="chart"></div>
      <div v-if="!error && !points.length" class="empty overlay">
        {{ loading ? '正在加载遥测数据…' : '暂无遥测数据（等待设备上报）' }}
      </div>
      <div v-if="!error && points.length && loading" class="badge-loading">同步中…</div>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { echarts, DARK_THEME, COLORS } from '../echarts'
import { getHistory } from '../api'
import { CHART_WINDOW_POINTS, HISTORY_HOURS, POLL_INTERVAL_MS } from '../config'
import { METRIC_COLOR, METRIC_LABEL, METRIC_UNIT } from '../metrics'

// 每条线的面积渐变基色（与 metrics.js 的 METRIC_COLOR 对应）
const AREA_RGB = { temperature: '251, 191, 36', humidity: '34, 211, 238', soil_moisture: '52, 211, 153', soil_temp: '255, 122, 89', co2: '167, 139, 250' }
const AREA_ALPHA = { temperature: 0.28, humidity: 0.26 }

const props = defineProps({
  devices: { type: Array, default: () => [] },
  // /api/meta 的 plots[]：用来按设备反查它所属地块的 metrics，决定画哪几条线
  plots: { type: Array, default: () => [] }
})

const chartEl = ref(null)
const deviceCode = ref('')
const hours = ref(HISTORY_HOURS)
const points = ref([])
const error = ref('')
const loading = ref(false)

let chart = null
let timer = null
let resizeObserver = null

const windowLabel = computed(() => `窗口保留最近 ${CHART_WINDOW_POINTS} 点 · ${POLL_INTERVAL_MS / 1000}s 刷新`)

// 当前设备的指标集：环境站/墒情站各只有自己那几项，C 区菇棚是温度·湿度·CO₂
const DEFAULT_METRICS = ['temperature', 'humidity', 'soil_moisture']
const activeMetrics = computed(() => {
  const d = props.devices.find((x) => x.device_code === deviceCode.value)
  if (!d) return DEFAULT_METRICS
  const plot = props.plots.find((p) => p.plot_code === d.plot_code)
  const declared = plot && Array.isArray(plot.metrics) ? plot.metrics : []
  // 未拿到 /api/meta（如 /legacy 不传 plots）时保持 V1 的三条线，视觉零回归
  if (!declared.length) return DEFAULT_METRICS
  // 地块声明的指标里，本设备 latest 真正有值的才画（环境站没有墒情、墒情站没有气温）
  const own = declared.filter((m) => d.latest && d.latest[m] !== null && d.latest[m] !== undefined)
  return own.length ? own : declared
})

function buildOption() {
  const ts = points.value.map((p) => p.ts)
  const fmt = (v) => (v === null || v === undefined ? null : Number(v))
  return {
    backgroundColor: 'transparent',
    grid: { left: 44, right: 52, top: 34, bottom: 30 },
    tooltip: {
      ...DARK_THEME.tooltip,
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: 'rgba(34, 211, 238, 0.55)' } }
    },
    legend: {
      data: activeMetrics.value.map((m) => `${METRIC_LABEL[m]}(${METRIC_UNIT[m]})`),
      top: 0,
      right: 0,
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { color: '#8aa6c4', fontSize: 11 }
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: ts,
      axisLine: DARK_THEME.axisLine,
      axisLabel: {
        color: '#5c7a99',
        fontSize: 10,
        hideOverlap: true,
        formatter: (v) => (typeof v === 'string' ? v.slice(11, 16) : v)
      },
      splitLine: { show: false }
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLine: { show: false },
      axisLabel: { color: '#5c7a99', fontSize: 10 },
      splitLine: DARK_THEME.splitLine
    },
    series: activeMetrics.value.map((m) => {
      const rgb = AREA_RGB[m] || '0, 229, 255'
      const line = {
        name: `${METRIC_LABEL[m]}(${METRIC_UNIT[m]})`,
        type: 'line',
        smooth: true,
        showSymbol: false,
        animationDuration: 400,
        // 墒情沿用 V1 的虚线样式，其余实线
        lineStyle: { width: 2, color: METRIC_COLOR[m] || COLORS.humidity, shadowColor: METRIC_COLOR[m] || COLORS.humidity, shadowBlur: 8, type: m === 'soil_moisture' ? 'dashed' : 'solid' },
        data: points.value.map((p) => fmt(p[m]))
      }
      // 面积渐变只给前两条线，避免多条叠加糊成一片
      if (activeMetrics.value.indexOf(m) < 2) {
        line.areaStyle = {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: `rgba(${rgb}, ${AREA_ALPHA[m] || 0.24})` },
            { offset: 1, color: `rgba(${rgb}, 0)` }
          ])
        }
      }
      return line
    })
  }
}

function render() {
  if (!chart) return
  chart.setOption(buildOption(), { notMerge: true })
}

function mergePoints(incoming) {
  const map = new Map(points.value.map((p) => [p.ts, p]))
  for (const p of incoming) map.set(p.ts, p)
  points.value = [...map.values()]
    .sort((a, b) => String(a.ts).localeCompare(String(b.ts)))
    .slice(-CHART_WINDOW_POINTS)
}

async function load({ silent = false } = {}) {
  if (!deviceCode.value) {
    points.value = []
    return
  }
  if (!silent) loading.value = true
  try {
    const res = await getHistory(deviceCode.value, hours.value, 5000, activeMetrics.value.join(','))
    mergePoints(Array.isArray(res?.points) ? res.points : [])
    error.value = ''
  } catch (err) {
    error.value = `遥测历史加载失败：${err.message}`
  } finally {
    loading.value = false
  }
}

const reload = () => load()

function startPolling() {
  stopPolling()
  timer = setInterval(() => load({ silent: true }), POLL_INTERVAL_MS)
}
function stopPolling() {
  if (timer) { clearInterval(timer); timer = null }
}

watch(deviceCode, () => { points.value = []; load() })
watch(hours, () => { points.value = []; load() })
watch(points, render)

onMounted(() => {
  chart = echarts.init(chartEl.value, null, { renderer: 'canvas' })
  render()
  if (props.devices.length) deviceCode.value = props.devices[0].device_code
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => chart && chart.resize())
    resizeObserver.observe(chartEl.value)
  }
  startPolling()
})

onBeforeUnmount(() => {
  stopPolling()
  if (resizeObserver) { resizeObserver.disconnect(); resizeObserver = null }
  if (chart) { chart.dispose(); chart = null } // 防内存泄漏
})

watch(() => props.devices, (list) => {
  if (!list.length) return
  if (!deviceCode.value || !list.some((d) => d.device_code === deviceCode.value)) {
    deviceCode.value = list[0].device_code
  }
})
</script>

<style scoped>
.realtime { display: flex; flex-direction: column; height: 100%; }
.controls { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 8px; }
.ctl { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--v2-sub); }
.ctl select { max-width: 220px; }
.chart-box { position: relative; flex: 1; min-height: 220px; }
.chart { width: 100%; height: 100%; min-height: 220px; }
.overlay { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; }
.badge-loading {
  position: absolute; top: 6px; left: 8px; font-size: 11px; color: var(--v2-cyan);
  background: rgba(34, 211, 238, 0.1); border: 1px solid rgba(34, 211, 238, 0.35);
  border-radius: 10px; padding: 1px 8px;
}
</style>
