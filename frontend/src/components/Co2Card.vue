<template>
  <div class="panel co2-card">
    <div class="panel-title">
      <span class="t-left"><i class="bar"></i>CO₂ 浓度</span>
      <span class="sub nowrap">{{ note }}</span>
    </div>
    <div class="co2-body">
      <span class="co2-value mono" :class="st.level">{{ fmt }}</span>
      <span class="co2-unit">ppm</span>
      <span class="tag" :class="tagClass">{{ st.text }}</span>
    </div>
    <div class="co2-bar">
      <span class="co2-fill" :class="st.level" :style="fillStyle"></span>
    </div>
    <p class="co2-hint mono nowrap">{{ rangeText }}</p>
  </div>
</template>

<script setup>
// CO₂ 卡片：C 区菇棚不渲染墒情仪表，改渲染本卡（棚内 CO₂ 是菇棚的核心指标）。
// 阈值优先取后端 thresholds.co2，缺失时用 metrics.js 的内置兜底并在副标题标注「内置阈值」。
import { computed } from 'vue'
import { CO2_FALLBACK_THRESHOLDS, evaluateMetric, fmt1 } from '../metrics'

const props = defineProps({
  value: { type: Number, default: null },
  thresholds: { type: Object, default: null }
})

const th = computed(() => (props.thresholds && Object.keys(props.thresholds).length ? props.thresholds : CO2_FALLBACK_THRESHOLDS))
const builtin = computed(() => !(props.thresholds && Object.keys(props.thresholds).length))
const note = computed(() => (builtin.value ? '内置阈值' : '后端阈值'))
const st = computed(() => evaluateMetric('co2', props.value, th.value))
const fmt = computed(() => fmt1(props.value))

const tagClass = computed(() => ({
  good: 'green',
  warn: 'warn',
  high: 'red',
  unknown: 'cyan'
}[st.value.level] || 'cyan'))

const hi = computed(() => {
  const c = th.value.critical_max
  const m = th.value.max
  return Math.max(Number(c || 0), Number(m || 0), 1000) * 1.2
})

const fillStyle = computed(() => {
  const v = props.value === null || props.value === undefined ? 0 : Number(props.value)
  const pct = Math.max(0, Math.min(100, (v / hi.value) * 100))
  return { width: pct.toFixed(1) + '%' }
})

const rangeText = computed(() => {
  const t = th.value
  const lo = t.min !== undefined && t.min !== null ? t.min : '--'
  const mx = t.max !== undefined && t.max !== null ? t.max : '--'
  const cm = t.critical_max !== undefined && t.critical_max !== null ? ' · >' + t.critical_max + ' 预警' : ''
  return '正常 ' + lo + ' ~ ' + mx + ' ppm' + cm
})
</script>

<style scoped>
.co2-card { flex: 0 0 auto; padding: 8px 11px; }
.co2-body { display: flex; align-items: baseline; gap: 6px; }
.co2-value { font-size: 26px; font-weight: 700; line-height: 1.1; }
.co2-value.good { color: var(--v2-green); }
.co2-value.warn { color: var(--v2-warn); }
.co2-value.high { color: var(--v2-red); }
.co2-value.unknown { color: var(--v2-sub); }
.co2-unit { font-size: 11px; color: var(--v2-sub); }
.co2-body .tag { margin-left: auto; }
.co2-bar { position: relative; height: 5px; margin: 7px 0 4px; border-radius: 3px; background: rgba(255, 255, 255, 0.08); overflow: hidden; }
.co2-fill { display: block; height: 100%; border-radius: 3px; background: var(--v2-green); transition: width 0.35s ease; }
.co2-fill.warn { background: var(--v2-warn); }
.co2-fill.high { background: var(--v2-red); }
.co2-fill.unknown { background: var(--v2-sub); }
.co2-hint { margin: 0; font-size: var(--v2-fs-aux); color: var(--v2-sub); }
</style>