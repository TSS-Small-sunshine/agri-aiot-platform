<template>
  <section class="panel gauge">
    <header class="panel-title">
      <span class="t-left"><i class="bar"></i>土壤墒情仪表</span>
      <span class="sub mono">{{ deviceCode || '未选择' }}</span>
    </header>

    <p v-if="error" class="err-inline">{{ error }}</p>

    <div class="gauge-box">
      <div ref="chartEl" class="chart"></div>
      <div v-if="!error && value === null" class="empty overlay">暂无墒情数据</div>
    </div>

    <div class="legend">
      <span><i class="chip crit"></i>严重 &lt;{{ critMin }}%</span>
      <span><i class="chip warn"></i>偏低 &lt;{{ warnMin }}%</span>
      <span><i class="chip ok"></i>正常 {{ warnMin }}~{{ max }}%</span>
      <span v-if="max < 100"><i class="chip over"></i>偏高 &gt;{{ max }}%</span>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { echarts, COLORS } from '../echarts'

const props = defineProps({
  value: { type: Number, default: null },
  deviceName: { type: String, default: '' },
  deviceCode: { type: String, default: '' },
  thresholds: { type: Object, default: () => ({}) },
  error: { type: String, default: '' }
})

const chartEl = ref(null)
let chart = null
let resizeObserver = null

const warnMin = computed(() => Number(props.thresholds?.min ?? 35))
const critMin = computed(() => Number(props.thresholds?.critical_min ?? 25))
const max = computed(() => Number(props.thresholds?.max ?? 80))

const state = computed(() => {
  const v = props.value
  if (v === null || v === undefined) return { text: '无数据', color: '#5c7a99' }
  if (v < critMin.value) return { text: '严重缺水', color: COLORS.red }
  if (v < warnMin.value) return { text: '墒情偏低', color: '#fbbf24' }
  if (v > max.value) return { text: '墒情偏高', color: '#a78bfa' }
  return { text: '墒情正常', color: COLORS.soil }
})

function buildOption() {
  const v = props.value === null || props.value === undefined ? 0 : Number(props.value)
  return {
    backgroundColor: 'transparent',
    series: [
      {
        type: 'gauge',
        startAngle: 210,
        endAngle: -30,
        min: 0,
        max: 100,
        radius: '92%',
        center: ['50%', '58%'],
        splitNumber: 5,
        progress: { show: true, width: 12, itemStyle: { color: state.value.color, shadowBlur: 12, shadowColor: state.value.color } },
        axisLine: { lineStyle: { width: 12, color: [[1, 'rgba(56, 89, 133, 0.32)']] } },
        pointer: { width: 4, length: '62%', itemStyle: { color: state.value.color } },
        anchor: { show: true, size: 10, itemStyle: { color: state.value.color, borderColor: '#0a1020', borderWidth: 2 } },
        axisTick: { distance: -14, length: 4, lineStyle: { color: 'rgba(90, 130, 175, 0.65)' } },
        splitLine: { distance: -18, length: 10, lineStyle: { color: 'rgba(90, 130, 175, 0.85)', width: 1.5 } },
        axisLabel: { distance: -6, color: '#5c7a99', fontSize: 10 },
        title: { offsetCenter: [0, '34%'], color: '#8aa6c4', fontSize: 12 },
        detail: {
          offsetCenter: [0, '4%'],
          color: state.value.color,
          fontSize: 26,
          fontWeight: 'bold',
          formatter: (val) => (props.value === null ? '--' : `${Number(val).toFixed(1)}%`)
        },
        data: [{ value: v, name: state.value.text }]
      }
    ]
  }
}

function render() {
  if (!chart) return
  chart.setOption(buildOption(), { notMerge: true })
}

watch([() => props.value, state, () => props.thresholds], render, { deep: true })

onMounted(() => {
  chart = echarts.init(chartEl.value, null, { renderer: 'canvas' })
  render()
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => chart && chart.resize())
    resizeObserver.observe(chartEl.value)
  }
})

onBeforeUnmount(() => {
  if (resizeObserver) { resizeObserver.disconnect(); resizeObserver = null }
  if (chart) { chart.dispose(); chart = null }
})
</script>

<style scoped>
.gauge { display: flex; flex-direction: column; height: 100%; }
.gauge-box { position: relative; flex: 1; min-height: 170px; }
.chart { width: 100%; height: 100%; min-height: 170px; }
.overlay { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; }
.legend { display: flex; flex-wrap: wrap; gap: 10px; font-size: 10.5px; color: var(--text-faint); margin-top: 4px; }
.chip { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 4px; }
.chip.crit { background: var(--red); }
.chip.warn { background: #fbbf24; }
.chip.ok { background: var(--green); }
.chip.over { background: #a78bfa; }
</style>
