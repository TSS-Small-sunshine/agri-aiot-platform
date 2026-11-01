<template>
  <section class="panel alerts">
    <header class="panel-title">
      <span class="t-left"><i class="bar"></i>阈值告警</span>
      <span class="sub">
        <span class="unacked mono">{{ unackedCount }}</span> 条未确认 / 共 {{ alerts.length }} 条
      </span>
    </header>

    <p v-if="error" class="err-inline">{{ error }}</p>

    <div v-if="loading && !alerts.length" class="sk-list">
      <div class="skeleton" style="height:42px" v-for="i in 2" :key="i"></div>
    </div>

    <p v-else-if="!alerts.length" class="empty">暂无告警，各项指标均在阈值内 ✓</p>

    <ul v-else class="list">
      <li v-for="a in alerts" :key="a.id" class="item" :class="{ unacked: !a.acked, critical: a.level === 'critical' && !a.acked }">
        <div class="head">
          <i class="dot" :class="a.acked ? 'unknown' : 'offline'"></i>
          <span class="lvl" :class="a.level">{{ a.level === 'critical' ? '严重' : '预警' }}</span>
          <span class="dev mono">{{ a.device_code }}</span>
          <span class="time mono">{{ shortTs(a.created_at) }}</span>
        </div>
        <div class="msg">{{ a.message }}</div>
        <div class="foot">
          <span class="metric mono">{{ metricLabel(a.metric) }} {{ fmt(a.value) }} / 阈值 {{ fmt(a.threshold) }}</span>
          <button v-if="!a.acked" class="btn danger" :disabled="ackingId === a.id" @click="onAck(a.id)">
            {{ ackingId === a.id ? '确认中…' : '一键确认' }}
          </button>
          <span v-else class="acked-tag">已确认</span>
        </div>
      </li>
    </ul>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  alerts: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' }
})
const emit = defineEmits(['ack'])

const ackingId = ref(null)
const unackedCount = computed(() => props.alerts.filter((a) => !a.acked).length)

const METRIC_LABEL = { temperature: '温度', humidity: '湿度', soil_moisture: '土壤墒情' }
const metricLabel = (m) => METRIC_LABEL[m] || m
const fmt = (v) => (v === null || v === undefined ? '--' : Number(v).toFixed(1))
const shortTs = (ts) => {
  if (!ts) return '--'
  const s = String(ts)
  return s.length >= 19 ? s.slice(5, 19).replace('T', ' ') : s
}

async function onAck(id) {
  ackingId.value = id
  try {
    emit('ack', id)
  } finally {
    ackingId.value = null
  }
}
</script>

<style scoped>
.alerts { display: flex; flex-direction: column; height: 100%; overflow: hidden; }
.list { list-style: none; margin: 0; padding: 0; overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 8px; }
.item {
  border: 1px solid var(--line-soft);
  border-left: 3px solid var(--text-faint);
  border-radius: var(--radius-sm);
  background: rgba(9, 17, 31, 0.55);
  padding: 7px 10px;
}
.item.unacked {
  border-left-color: var(--red);
  border-color: rgba(244, 63, 94, 0.45);
  background: var(--red-soft);
  box-shadow: var(--glow-red);
  animation: alert-pulse 2.2s ease-in-out infinite;
}
.item.unacked.critical { border-color: rgba(244, 63, 94, 0.75); }
@keyframes alert-pulse {
  0%, 100% { box-shadow: 0 0 10px rgba(244, 63, 94, 0.3); }
  50% { box-shadow: 0 0 18px rgba(244, 63, 94, 0.6); }
}
.head { display: flex; align-items: center; gap: 7px; font-size: 11px; }
.lvl { border-radius: 9px; padding: 0 7px; border: 1px solid; font-size: 10px; }
.lvl.warning { color: #fbbf24; border-color: rgba(251, 191, 36, 0.5); background: rgba(251, 191, 36, 0.1); }
.lvl.critical { color: var(--red); border-color: rgba(244, 63, 94, 0.6); background: rgba(244, 63, 94, 0.16); }
.dev { color: var(--text-sub); }
.time { margin-left: auto; color: var(--text-faint); }
.msg { font-size: 12.5px; margin: 5px 0; color: var(--text-main); }
.foot { display: flex; align-items: center; gap: 10px; }
.metric { font-size: 11px; color: var(--text-sub); flex: 1; }
.acked-tag { font-size: 11px; color: var(--text-faint); }
.sk-list { display: flex; flex-direction: column; gap: 8px; }
</style>
