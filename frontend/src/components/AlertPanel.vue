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
// 指标中文名统一取自 metrics.js，新增指标（co2）只需在注册表登记一次
import { metricLabel as labelOf } from '../metrics'

const props = defineProps({
  alerts: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' }
})
const emit = defineEmits(['ack'])

const ackingId = ref(null)
const unackedCount = computed(() => props.alerts.filter((a) => !a.acked).length)

const metricLabel = (m) => labelOf(m)
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
/* V2.1 左栏紧凑形态：变量全部改用 --v2-*（V1 变量只在 .legacy-scope 内定义，在 V2 下会作废） */
.alerts { display: flex; flex-direction: column; height: 100%; min-height: 0; overflow: hidden; }
.list { list-style: none; margin: 0; padding: 0; overflow-y: auto; flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 6px; }
.item {
  border: 1px solid var(--v2-line-soft);
  border-left: 3px solid var(--v2-sub);
  border-radius: var(--v2-r-sm);
  background: rgba(15, 23, 42, 0.55);
  padding: 6px 8px;
}
.item.unacked {
  border-left-color: var(--v2-red);
  border-color: rgba(255, 59, 48, 0.45);
  background: rgba(255, 59, 48, 0.10);
  animation: alert-pulse 2.2s ease-in-out infinite;
}
.item.unacked.critical { border-color: rgba(255, 59, 48, 0.75); }
@keyframes alert-pulse {
  0%, 100% { box-shadow: 0 0 10px rgba(255, 59, 48, 0.3); }
  50% { box-shadow: 0 0 18px rgba(255, 59, 48, 0.6); }
}
.head { display: flex; align-items: center; gap: 6px; font-size: 10.5px; }
.lvl { border-radius: 9px; padding: 0 6px; border: 1px solid; font-size: 9.5px; }
.lvl.warning { color: var(--v2-warn); border-color: rgba(255, 179, 0, 0.5); background: rgba(255, 179, 0, 0.1); }
.lvl.critical { color: var(--v2-red); border-color: rgba(255, 59, 48, 0.6); background: rgba(255, 59, 48, 0.16); }
.dev { color: var(--v2-sub); }
.time { margin-left: auto; color: var(--v2-sub); }
.msg { font-size: 11.5px; margin: 4px 0; color: var(--v2-text); }
.foot { display: flex; align-items: center; gap: 8px; }
.metric { font-size: var(--v2-fs-aux); color: var(--v2-sub); flex: 1; }
.acked-tag { font-size: var(--v2-fs-aux); color: var(--v2-sub); }
.sk-list { display: flex; flex-direction: column; gap: 8px; }
</style>
