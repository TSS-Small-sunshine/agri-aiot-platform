<template>
  <div class="ap">
    <header class="ap-top">
      <div class="ap-brand">
        <span class="ap-badge-mode">大字模式</span>
        <span class="ap-sub">{{ subLine }}</span>
      </div>
      <button class="ap-close" type="button" @click="$emit('close')">退出大字模式</button>
    </header>

    <main class="ap-list">
      <section v-for="c in cards" :key="c.key" class="ap-card" :class="c.kind">
        <div class="ap-card-head">
          <span class="ap-tag">{{ c.badge }}</span>
          <span class="ap-time mono">{{ c.time }}</span>
        </div>
        <h2 class="ap-card-title">{{ c.title }}</h2>
        <p class="ap-card-body">{{ c.body }}</p>
        <p v-if="c.hint" class="ap-card-hint">{{ c.hint }}</p>
      </section>
    </main>

    <footer class="ap-foot">
      <span>数据来源 /api/alerts（未确认优先）与最近一次 /api/reasoning/simulate</span>
      <span class="mono">在线设备 {{ onlineCount }}/{{ devices.length }} · 未确认告警 {{ unackedCount }} 条</span>
    </footer>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { metricLabel } from '../metrics'

const props = defineProps({
  alerts: { type: Array, default: () => [] },
  reasoning: { type: Object, default: null },
  devices: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false }
})

defineEmits(['close'])

// 指标名映射与 AlertPanel 共用 metrics.js 注册表，C 区 co2 也能显示中文名

const onlineCount = computed(() => props.devices.filter((d) => d.status === 'online').length)
const unackedCount = computed(() => props.alerts.filter((a) => !a.acked).length)

// 只保留最高优先级：未确认 → critical 优先 → 时间倒序；已确认的不进大字视图
const topAlerts = computed(() => {
  const rank = { critical: 0, warning: 1 }
  return props.alerts
    .filter((a) => !a.acked)
    .slice()
    .sort((a, b) => {
      const ra = rank[a.level] ?? 2
      const rb = rank[b.level] ?? 2
      if (ra !== rb) return ra - rb
      return String(b.created_at || '').localeCompare(String(a.created_at || ''))
    })
    .slice(0, 5)
})

// 干预建议取最近一次推演里的绿色 plan 分支（真实数据，无写死文案）
const planNodes = computed(() => {
  const nodes = props.reasoning?.tree?.nodes || []
  return nodes.filter((n) => n.type === 'plan')
})

const subLine = computed(() => {
  const name = props.reasoning?.context?.plot?.name || props.reasoning?.plot_code
  return name ? `最近推演地块：${name}` : '尚未推演 · 仅显示实时告警'
})

function shortTs(ts) {
  const s = String(ts || '')
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : '--'
}

const num = (v) => (v === null || v === undefined ? '--' : Number(v).toFixed(1))

const cards = computed(() => {
  const out = []

  for (const a of topAlerts.value) {
    const critical = a.level === 'critical'
    out.push({
      key: `alert-${a.id}`,
      kind: critical ? 'danger' : 'warn',
      badge: critical ? '紧急告警' : '预警',
      time: shortTs(a.created_at),
      title: `${metricLabel(a.metric)} ${num(a.value)}`,
      body: a.message || `${a.device_code} 的 ${METRIC_LABEL[a.metric] || a.metric} 超出阈值 ${num(a.threshold)}`,
      hint: `设备 ${a.device_code} · 阈值 ${num(a.threshold)}`
    })
  }

  for (const n of planNodes.value) {
    const eff = n.effect || {}
    const hintParts = []
    if (n.command?.device_code) hintParts.push(`目标设备 ${n.command.device_code}`)
    if (eff.soil_moisture_delta != null) hintParts.push(`墒情回升 ${num(eff.soil_moisture_delta)}%`)
    if (eff.yield_recover_pct != null) hintParts.push(`挽回产量 ${num(eff.yield_recover_pct)}%`)
    out.push({
      key: `plan-${n.id}`,
      kind: 'good',
      badge: '干预建议',
      time: shortTs(props.reasoning?.generated_at),
      title: n.label,
      body: n.sub || '按建议执行可缓解当前胁迫',
      hint: hintParts.join(' · ')
    })
  }

  if (!out.length) {
    out.push({
      key: 'normal',
      kind: 'good',
      badge: '状态正常',
      time: shortTs(new Date().toISOString()),
      title: '当前正常',
      body: props.loading ? '正在加载实时数据…' : '暂无未确认告警，也没有待执行的干预建议。',
      hint: `在线设备 ${onlineCount.value}/${props.devices.length}`
    })
  }

  return out
})
</script>

<style scoped>
/* 适老化：正文 ≥28px、标题 ≥40px，高对比度，绿底/红底大卡 */
.ap { display: flex; flex-direction: column; gap: 18px; min-height: 100%; padding: 18px 20px 24px; }

.ap-top { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.ap-brand { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.ap-badge-mode {
  font-size: 30px; font-weight: 700; color: #06110a;
  background: var(--v2-cyan); border-radius: 8px; padding: 6px 16px;
}
.ap-sub { font-size: 22px; color: var(--v2-sub); }
.ap-close {
  font-family: inherit; font-size: 24px; font-weight: 700; cursor: pointer;
  color: var(--v2-text); background: rgba(255, 255, 255, 0.06);
  border: 2px solid var(--v2-line-color); border-radius: 10px; padding: 12px 26px;
}
.ap-close:hover { background: rgba(0, 229, 255, 0.14); border-color: var(--v2-cyan); }

.ap-list { flex: 1; display: flex; flex-direction: column; gap: 18px; }

.ap-card { border-radius: 14px; padding: 22px 26px; border: 3px solid transparent; }
.ap-card.good { background: #0d3b22; border-color: var(--v2-green); }
.ap-card.danger { background: #4a100c; border-color: var(--v2-red); }
.ap-card.warn { background: #4a3405; border-color: var(--v2-warn); }

.ap-card-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.ap-tag {
  font-size: 24px; font-weight: 700; color: #ffffff;
  background: rgba(0, 0, 0, 0.32); border-radius: 6px; padding: 4px 14px;
}
.ap-time { font-size: 22px; color: rgba(255, 255, 255, 0.78); }

.ap-card-title { margin: 12px 0 8px; font-size: 44px; line-height: 1.25; color: #ffffff; letter-spacing: 0.02em; }
.ap-card-body { margin: 0; font-size: 30px; line-height: 1.55; color: #ffffff; }
.ap-card-hint { margin: 12px 0 0; font-size: 24px; color: rgba(255, 255, 255, 0.82); }

.ap-foot {
  display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap;
  font-size: 20px; color: var(--v2-sub); border-top: 1px solid var(--v2-line-soft); padding-top: 12px;
}
</style>
