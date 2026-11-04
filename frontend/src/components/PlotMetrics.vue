<template>
  <div class="panel kpi-panel">
    <div class="panel-title">
      <span class="t-left"><i class="bar"></i>核心指标</span>
      <span class="sub nowrap">{{ plotName }} · 近 {{ SUMMARY_HOURS }}h</span>
    </div>
    <div class="kpi-row" :style="rowStyle">
      <div v-for="m in metrics" :key="m" class="kpi-cell">
        <span class="kc-label nowrap">{{ label(m) }}</span>
        <span class="kc-value mono" :class="state(m).level">
          {{ fmt(value(m)) }}<em>{{ unit(m) }}</em>
        </span>
        <span class="kc-state" :class="state(m).level">{{ state(m).text }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
// 核心指标卡：渲染哪几个指标完全由 /api/meta 的 plots[].metrics 决定。
// A/B 区是 temperature/humidity/soil_moisture/soil_temp，C 区菇棚是 temperature/humidity/co2，
// 因此这里不能用固定的三列布局，列数随 metrics 长度变化。
import { computed } from 'vue'
import { DEFAULT_METRICS, evaluateMetric, fmt1, metricLabel, metricThreshold, metricUnit, valueWithSummary } from '../metrics'
import { SUMMARY_HOURS } from '../config'

const props = defineProps({
  plot: { type: Object, default: null },
  latest: { type: Array, default: () => [] },
  summary: { type: Object, default: null },
  thresholds: { type: Object, default: () => ({}) }
})

const metrics = computed(() => (props.plot && props.plot.metrics && props.plot.metrics.length ? props.plot.metrics : DEFAULT_METRICS))
const plotName = computed(() => (props.plot && (props.plot.name || props.plot.plot_name)) || (props.plot && props.plot.plot_code) || '--')
// 列数随 metrics 数量变化，但每列有最小宽度：左栏窄时自动折行而不是把数值挤到溢出
const rowStyle = computed(() => ({ gridTemplateColumns: 'repeat(auto-fit, minmax(88px, 1fr))' }))

function value(metric) {
  const code = props.plot ? props.plot.plot_code : ''
  return valueWithSummary(props.latest, code, metric, props.summary)
}

function state(metric) {
  return evaluateMetric(metric, value(metric), metricThreshold(metric, props.plot, props.thresholds))
}

function fmt(v) { return fmt1(v) }
const label = metricLabel
const unit = metricUnit
</script>

<style scoped>
.kpi-panel { flex: 0 0 auto; padding: 8px 11px; }
.kpi-row { display: grid; gap: 8px; }
.kpi-cell { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.kc-label { font-size: var(--v2-fs-aux); color: var(--v2-sub); }
.kc-value { font-size: var(--v2-fs-value); font-weight: 700; line-height: 1.15; }
.kc-value em { font-size: 11px; font-style: normal; font-weight: 400; color: var(--v2-sub); margin-left: 2px; }
.kc-value.temp { color: var(--v2-warn); }
.kc-value.humi { color: var(--v2-cyan); }
.kc-value.soil { color: var(--v2-green); }
.kc-state { font-size: var(--v2-fs-aux); color: var(--v2-sub); }
.kc-state.good { color: var(--v2-green); }
.kc-state.warn { color: var(--v2-warn); }
.kc-state.high { color: var(--v2-red); }
</style>