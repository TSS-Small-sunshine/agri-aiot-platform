<template>
  <section class="panel devices">
    <header class="panel-title">
      <span class="t-left"><i class="bar"></i>设备在线状态</span>
      <span class="sub mono">{{ onlineCount }}/{{ devices.length }} 在线</span>
    </header>

    <p v-if="error" class="err-inline">{{ error }}</p>

    <div v-if="loading && !devices.length" class="sk-list">
      <div v-for="i in 3" :key="i" class="sk-row">
        <div class="skeleton" style="width:100%;height:58px"></div>
      </div>
    </div>

    <p v-else-if="!devices.length" class="empty">暂无设备（后端 /api/devices 无数据）</p>

    <ul v-else class="list">
      <li
        v-for="d in devices"
        :key="d.device_code"
        class="item"
        :class="{ offline: d.status !== 'online', focused: d.device_code === focusDevice }"
        @click="$emit('focus', d.device_code)"
      >
        <div class="row1">
          <i class="dot" :class="d.status === 'online' ? 'online' : 'offline'"></i>
          <span class="name" :title="d.name">{{ d.name }}</span>
          <span class="tag" :class="d.status === 'online' ? 'ok' : 'bad'">
            {{ d.status === 'online' ? '在线' : '离线' }}
          </span>
        </div>
        <div class="row2 mono">
          <span>{{ d.device_code }}</span>
          <span class="plot">{{ d.plot_name || d.plot_code }}</span>
        </div>
        <div class="row3">
          <span class="metric temp"><b>{{ num(d.latest?.temperature) }}</b>℃</span>
          <span class="metric humi"><b>{{ num(d.latest?.humidity) }}</b>%RH</span>
          <span class="metric soil"><b>{{ num(d.latest?.soil_moisture) }}</b>%</span>
          <span class="metric batt">电量 <b>{{ num(d.latest?.battery) }}</b>%</span>
        </div>
        <div class="row4 mono">最后上报：{{ shortTs(d.last_seen) }}</div>
      </li>
    </ul>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  devices: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  focusDevice: { type: String, default: '' }
})
defineEmits(['focus'])

const onlineCount = computed(() => props.devices.filter((d) => d.status === 'online').length)

const num = (v) => (v === null || v === undefined ? '--' : Number(v).toFixed(1))
const shortTs = (ts) => {
  if (!ts) return '--'
  const s = String(ts)
  return s.length >= 19 ? s.slice(5, 19).replace('T', ' ') : s
}
</script>

<style scoped>
.devices { display: flex; flex-direction: column; height: 100%; overflow: hidden; }
.list { list-style: none; margin: 0; padding: 0; overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 8px; }
.item {
  background: rgba(9, 17, 31, 0.55);
  border: 1px solid var(--line-soft);
  border-left: 3px solid var(--green);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
}
.item:hover { background: rgba(26, 41, 68, 0.7); }
.item.offline { border-left-color: var(--red); }
.item.focused { border-color: var(--cyan); box-shadow: var(--glow-cyan); }
.row1 { display: flex; align-items: center; gap: 7px; }
.name { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.tag { font-size: 10px; border-radius: 9px; padding: 1px 7px; border: 1px solid; }
.tag.ok { color: var(--green); border-color: rgba(52, 211, 153, 0.5); background: rgba(52, 211, 153, 0.1); }
.tag.bad { color: var(--red); border-color: rgba(244, 63, 94, 0.5); background: var(--red-soft); }
.row2 { display: flex; justify-content: space-between; font-size: 10.5px; color: var(--text-faint); margin: 3px 0 5px; }
.row3 { display: flex; flex-wrap: wrap; gap: 10px; font-size: 11px; color: var(--text-sub); }
.metric b { font-family: var(--font-mono); font-size: 12.5px; }
.metric.temp b { color: #fbbf24; }
.metric.humi b { color: var(--cyan); }
.metric.soil b { color: var(--green); }
.row4 { font-size: 10.5px; color: var(--text-faint); margin-top: 4px; }
.sk-list { display: flex; flex-direction: column; gap: 8px; }
</style>
