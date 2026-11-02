<template>
  <div class="cmd">
    <button class="btn cmd-btn" type="button" :disabled="busy" @click="run">
      {{ busy ? '下发中…' : '一键执行指令' }}
    </button>
    <div class="cmd-state">
      <span class="dot" :class="dotClass"></span>
      <span class="cmd-label" :class="dotClass">{{ statusLabel }}</span>
      <span v-if="cmdId" class="cmd-id mono nowrap" :title="cmdId">{{ cmdId.slice(0, 8) }}</span>
    </div>
    <p v-if="error" class="err-inline">{{ error }}</p>
    <p v-if="ackAt" class="cmd-ack mono">回执 {{ shortTs(ackAt) }}</p>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { executeCommand, getCommandHistory } from '../api'
import { COMMAND_HISTORY_LIMIT, POLL_INTERVAL_MS } from '../config'
import { pushToast } from '../toast'

const props = defineProps({
  // 推演树上的绿色干预节点：command.action / command.params / command.device_code
  node: { type: Object, required: true },
  plotCode: { type: String, default: '' },
  reasoningId: { type: String, default: '' },
  // 父级保存的指令记录：重新推演后组件会被重建，靠它恢复状态点而不是回落「未下发」
  record: { type: Object, default: null }
})

const emit = defineEmits(['executed'])

const busy = ref(false)
const error = ref('')
const cmdId = ref('')
const status = ref('')
const ackAt = ref('')
let timer = null

const dotClass = computed(() => {
  if (status.value === 'executed') return 'online'
  if (status.value === 'timeout') return 'offline'
  if (status.value === 'dispatched') return 'warn'
  return 'unknown'
})

const statusLabel = computed(() => {
  const map = { dispatched: '已下发待回执', executed: '已执行', timeout: '回执超时' }
  return map[status.value] || '未下发'
})

function shortTs(ts) {
  const s = String(ts || '')
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/)
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6]}` : s
}

async function run() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    // 推演树里指令有两种挂载方式：绿色 plan 节点把指令放在 node.command；
    // 若节点本身就是指令节点（形如 {action, params, device_code}），则退回节点自身。
    const c = props.node.command || props.node || {}
    const res = await executeCommand({
      reasoning_id: props.reasoningId || null,
      plot_code: props.plotCode,
      device_code: c.device_code || props.node.device_code || '',
      node_id: props.node.id,
      action: c.action,
      params: c.params || {}
    })
    cmdId.value = res.command_id
    status.value = res.status || 'dispatched'
    pushToast(`指令已通过 MQTT 模拟下发（${res.command_id}）`, { kind: 'ok', ttl: 6000 })
    emit('executed', res)
    startPolling()
  } catch (e) {
    error.value = `指令下发失败：${e.message}`
  } finally {
    busy.value = false
  }
}

async function poll() {
  if (!cmdId.value) return
  try {
    const res = await getCommandHistory(COMMAND_HISTORY_LIMIT)
    const hit = (res.items || []).find((it) => it.command_id === cmdId.value)
    if (!hit) return
    const changed = hit.status !== status.value
    status.value = hit.status
    ackAt.value = hit.ack_at || ''
    // 状态变化要回传父级，否则对话流里的指令行会一直停在 dispatched
    if (changed) emit('executed', { command_id: cmdId.value, status: status.value, ack_at: ackAt.value })
    // 终态（executed / timeout）才停止轮询，dispatched 继续等回执
    if (hit.status === 'executed' || hit.status === 'timeout') stopPolling()
  } catch (e) {
    error.value = `指令状态查询失败：${e.message}`
  }
}

function startPolling() {
  stopPolling()
  timer = setInterval(poll, POLL_INTERVAL_MS)
  poll()
}

function stopPolling() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

onMounted(() => {
  // 组件被重建时（例如父级重新推演）从父级记录里恢复，未到终态则继续轮询
  if (props.record?.command_id) {
    cmdId.value = props.record.command_id
    status.value = props.record.status || 'dispatched'
    if (status.value === 'dispatched') startPolling()
  }
})

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.cmd { margin-top: 6px; display: flex; flex-direction: column; gap: 4px; align-items: flex-start; }
.cmd-btn { font-size: 11.5px; padding: 3px 9px; }
.cmd-state { display: flex; align-items: center; gap: 5px; font-size: 10.5px; color: var(--v2-sub); }
.cmd-label.online { color: var(--v2-green); }
.cmd-label.offline { color: var(--v2-red); }
.cmd-label.warn { color: var(--v2-warn); }
.cmd-id { max-width: 90px; font-size: 10px; color: var(--v2-sub); }
.cmd-ack { margin: 0; font-size: 10px; color: var(--v2-sub); }
.cmd .err-inline { margin: 0; }
</style>
