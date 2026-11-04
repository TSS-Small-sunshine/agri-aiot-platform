<template>
  <div class="panel pg-gauge">
    <div class="panel-title">
      <span class="t-left"><i class="bar"></i>土壤墒情仪表</span>
      <span class="sub nowrap">{{ deviceCode || '--' }}</span>
    </div>
    <div class="gauge-box">
      <div ref="chartEl" class="gauge-chart"></div>
      <p v-if="state.level === 'unknown'" class="empty overlay">暂无墒情数据</p>
    </div>
    <p class="gauge-legend mono nowrap">
      <span class="chip crit">&lt;{{ critMin }} 严重缺水</span>
      <span class="chip warn">{{ critMin }}~{{ warnMin }} 偏低</span>
      <span class="chip ok">{{ warnMin }}~{{ max }} 正常</span>
      <span class="chip over">&gt;{{ max }} 偏高</span>
    </p>
  </div>
</template>

<script setup>
// 墒情仪表：只在地块的 metrics 里声明了 soil_moisture 时由父级挂载。
// C 区菇棚没有土壤指标，父级改挂 Co2Card，因此这里不需要处理无墒情场景。
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { echarts, PALETTE } from '../echarts'

const props = defineProps({
  value: { type: Number, default: null },
  deviceCode: { type: String, default: '' },
  thresholds: { type: Object, default: () => ({}) }
})

const chartEl = ref(null)
let chart = null
let ro = null
let lastBox = { w: 0, h: 0 }

const warnMin = computed(() => (props.thresholds.min !== undefined && props.thresholds.min !== null ? props.thresholds.min : 35))
const critMin = computed(() => (props.thresholds.critical_min !== undefined && props.thresholds.critical_min !== null ? props.thresholds.critical_min : 25))
const max = computed(() => (props.thresholds.max !== undefined && props.thresholds.max !== null ? props.thresholds.max : 80))

const state = computed(() => {
  const v = props.value
  if (v === null || v === undefined || Number.isNaN(Number(v))) return { text: '无数据', color: PALETTE.sub, level: 'unknown' }
  const n = Number(v)
  if (n < critMin.value) return { text: '严重缺水', color: PALETTE.red, level: 'high' }
  if (n < warnMin.value) return { text: '墒情偏低', color: PALETTE.warn, level: 'warn' }
  if (n > max.value) return { text: '墒情偏高', color: PALETTE.cyan, level: 'warn' }
  return { text: '墒情正常', color: PALETTE.green, level: 'good' }
})

function chartBox() {
  const el = chartEl.value
  return { w: Math.max(120, Math.round((el && el.clientWidth) || 240)), h: Math.max(80, Math.round((el && el.clientHeight) || 120)) }
}

function buildOption() {
  const v = props.value === null || props.value === undefined ? null : Number(props.value)
  return {
    series: [{
      type: 'gauge',
      startAngle: 210,
      endAngle: -30,
      min: 0,
      max: 100,
      radius: '92%',
      center: ['50%', '62%'],
      progress: { show: true, width: 8, itemStyle: { color: state.value.color } },
      axisLine: { lineStyle: { width: 8, color: [[1, 'rgba(255,255,255,0.10)']] } },
      axisTick: { show: false },
      splitLine: { length: 6, lineStyle: { color: 'rgba(255,255,255,0.18)' } },
      axisLabel: { show: false },
      pointer: { width: 3, length: '58%', itemStyle: { color: state.value.color } },
      anchor: { show: true, size: 6, itemStyle: { color: state.value.color } },
      detail: {
        valueAnimation: true,
        offsetCenter: [0, '32%'],
        formatter: function (val) { return val === null || val === undefined ? '--' : Number(val).toFixed(1) + '%' },
        color: state.value.color,
        fontSize: 18,
        fontWeight: 700
      },
      title: { offsetCenter: [0, '62%'], color: PALETTE.sub, fontSize: 10 },
      data: [{ value: v, name: state.value.text }]
    }]
  }
}

function teardown() {
  if (ro) { ro.disconnect(); ro = null }
  if (chart) { chart.dispose(); chart = null }
}

async function render() {
  await nextTick()
  const el = chartEl.value
  if (!el || !el.clientWidth || !el.clientHeight) return
  if (chart && chart.getDom() !== el) teardown()
  if (!chart) chart = echarts.init(el, null, { renderer: 'canvas' })
  chart.setOption(buildOption(), true)
  lastBox = chartBox()
}

watch(() => [props.value, props.thresholds], render, { deep: true, immediate: true })

onMounted(() => {
  render()
  ro = new ResizeObserver(() => {
    // 容器被 display:none 隐藏时 clientWidth/Height 为 0，直接跳过以免把画布压成 100×0
    if (!chartEl.value || !chartEl.value.clientWidth || !chartEl.value.clientHeight) return
    const box = chartBox()
    if (box.w === lastBox.w && box.h === lastBox.h) return
    lastBox = box
    if (chart) chart.resize()
  })
  ro.observe(chartEl.value)
})

onBeforeUnmount(teardown)
</script>

<style scoped>
.pg-gauge { flex: 0 0 auto; padding: 8px 11px; }
.gauge-box { position: relative; height: 108px; }
.gauge-chart { width: 100%; height: 100%; }
.empty.overlay { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: transparent; }
.gauge-legend { display: flex; flex-wrap: wrap; gap: 3px 8px; margin: 4px 0 0; font-size: 9.5px; color: var(--v2-sub); }
.gauge-legend .chip { padding: 0 4px; border-radius: 3px; border: 1px solid transparent; }
.gauge-legend .chip.crit { color: var(--v2-red); border-color: rgba(255, 59, 48, 0.4); }
.gauge-legend .chip.warn { color: var(--v2-warn); border-color: rgba(255, 179, 0, 0.4); }
.gauge-legend .chip.ok { color: var(--v2-green); border-color: rgba(0, 230, 118, 0.4); }
.gauge-legend .chip.over { color: var(--v2-cyan); border-color: rgba(0, 229, 255, 0.4); }
</style>