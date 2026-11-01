<template>
  <section class="panel aichat">
    <header class="panel-title">
      <span class="t-left"><i class="bar"></i>AI 农技助手</span>
      <span class="sub">
        <span v-if="degraded" class="mock-badge">Mock 模式</span>
        <span v-else-if="configured" class="live-badge">在线模型</span>
        <span v-else class="mock-badge">未配置 Key</span>
      </span>
    </header>

    <p v-if="error" class="err-inline">{{ error }}</p>
    <p v-if="modelsError" class="err-inline">{{ modelsError }}</p>

    <div class="body">
      <div class="main">
        <div class="controls">
          <label class="ctl">
            <span>模型</span>
            <select v-model="model" :disabled="!models.length">
              <option v-if="!models.length" value="">无可用模型</option>
              <option v-for="m in models" :key="m.id" :value="m.id">
                {{ m.label }}（{{ m.source }}）
              </option>
            </select>
          </label>
          <button class="btn" :disabled="loading || !models.length" @click="loadModels">刷新模型</button>
        </div>

        <div ref="scrollEl" class="messages">
          <div v-if="!messages.length" class="empty">
            向 AI 农技助手提问，例如「柑橘叶子发黄怎么办」「墒情低于 35% 要浇水吗」
          </div>
          <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
            <div class="bubble">
              <div class="meta mono" v-if="m.role === 'assistant'">
                {{ m.model }} · {{ m.latency_ms }}ms
                <span v-if="m.degraded" class="degraded-tag">降级</span>
              </div>
              <div class="text">{{ m.text }}</div>
            </div>
          </div>
          <div v-if="sending" class="msg assistant">
            <div class="bubble"><span class="typing"><i></i><i></i><i></i></span></div>
          </div>
        </div>

        <div class="compose">
          <textarea
            v-model="question"
            rows="2"
            placeholder="输入问题，Ctrl + Enter 发送"
            :disabled="loading"
            @keydown.ctrl.enter.prevent="send"
          ></textarea>
          <button class="btn" :disabled="loading || !question.trim()" @click="send">
            {{ loading ? '发送中…' : '发送' }}
          </button>
        </div>
      </div>

      <aside class="history">
        <div class="history-head">
          <span>历史记录</span>
          <button class="btn" :disabled="historyLoading" @click="loadHistory">刷新</button>
        </div>
        <p v-if="historyError" class="err-inline">{{ historyError }}</p>
        <div v-if="historyLoading && !history.length" class="sk-list">
          <div class="skeleton" style="height:34px" v-for="i in 3" :key="i"></div>
        </div>
        <p v-else-if="!history.length" class="empty">暂无历史对话</p>
        <ul v-else class="history-list">
          <li v-for="h in history" :key="h.id" class="hitem" @click="replay(h)">
            <div class="hq">{{ h.question }}</div>
            <div class="ha">{{ h.answer }}</div>
            <div class="hmeta mono">
              {{ h.model }}<span v-if="h.degraded" class="degraded-tag">降级</span> · {{ shortTs(h.created_at) }}
            </div>
          </li>
        </ul>
      </aside>
    </div>
  </section>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { aiChat, getAiHistory, getAiModels } from '../api'
import { AI_HISTORY_LIMIT } from '../config'

const emit = defineEmits(['error'])

const sessionId = `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`

const models = ref([])
const model = ref('')
const configured = ref(false)
const degraded = ref(true)
const messages = ref([])
const question = ref('')
const loading = ref(false)
const sending = ref(false)
const error = ref('')
const modelsError = ref('')
const history = ref([])
const historyLoading = ref(false)
const historyError = ref('')
const scrollEl = ref(null)

const shortTs = (ts) => (ts && String(ts).length >= 19 ? String(ts).slice(5, 19).replace('T', ' ') : ts || '--')

function report(msg) {
  error.value = msg
  emit('error', msg)
}

async function loadModels() {
  try {
    const res = await getAiModels()
    models.value = Array.isArray(res?.items) ? res.items : []
    configured.value = !!res?.configured
    degraded.value = !!res?.degraded
    modelsError.value = res?.error ? `模型发现失败，已回落到 Mock 列表：${res.error}` : ''
    if (!model.value || !models.value.some((m) => m.id === model.value)) {
      model.value = res?.default_model || models.value[0]?.id || ''
    }
  } catch (err) {
    modelsError.value = `模型列表加载失败：${err.message}`
    emit('error', modelsError.value)
  }
}

async function loadHistory() {
  historyLoading.value = true
  try {
    const res = await getAiHistory(AI_HISTORY_LIMIT)
    history.value = Array.isArray(res?.items) ? res.items : []
    historyError.value = ''
  } catch (err) {
    historyError.value = `历史记录加载失败：${err.message}`
  } finally {
    historyLoading.value = false
  }
}

function replay(h) {
  messages.value.push({ role: 'user', text: h.question })
  messages.value.push({
    role: 'assistant',
    text: h.answer || '（无回答）',
    model: h.model,
    latency_ms: h.latency_ms,
    degraded: !!h.degraded
  })
  scrollToEnd()
}

async function scrollToEnd() {
  await nextTick()
  if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
}

async function send() {
  const q = question.value.trim()
  if (!q || loading.value) return
  error.value = ''
  messages.value.push({ role: 'user', text: q })
  question.value = ''
  loading.value = true
  sending.value = true
  scrollToEnd()
  try {
    const res = await aiChat(q, sessionId, model.value || undefined)
    messages.value.push({
      role: 'assistant',
      text: res?.answer || '（空回答）',
      model: res?.model || 'unknown',
      latency_ms: res?.latency_ms ?? 0,
      degraded: !!res?.degraded
    })
    if (res?.degraded) degraded.value = true
    if (res?.error) report(`AI 服务降级：${res.error}`)
    loadHistory()
  } catch (err) {
    report(`AI 对话请求失败：${err.message}`)
    messages.value.push({ role: 'assistant', text: `请求失败：${err.message}`, model: '-', latency_ms: 0, degraded: true })
  } finally {
    loading.value = false
    sending.value = false
    scrollToEnd()
  }
}

onMounted(() => {
  loadModels()
  loadHistory()
})
</script>

<style scoped>
.aichat { display: flex; flex-direction: column; height: 100%; }
.body { display: flex; gap: 12px; flex: 1; min-height: 0; }
.main { display: flex; flex-direction: column; flex: 1; min-width: 0; }
.controls { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.ctl { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-sub); }
.ctl select { max-width: 230px; }
.messages {
  flex: 1;
  min-height: 120px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 4px 2px;
}
.msg { display: flex; }
.msg.user { justify-content: flex-end; }
.bubble {
  max-width: 82%;
  border-radius: 10px;
  padding: 7px 10px;
  font-size: 12.5px;
  border: 1px solid var(--line-soft);
  background: rgba(9, 17, 31, 0.6);
}
.msg.user .bubble {
  background: rgba(34, 211, 238, 0.12);
  border-color: rgba(34, 211, 238, 0.42);
}
.msg.assistant .bubble { border-left: 2px solid var(--green); }
.meta { font-size: 10px; color: var(--text-faint); margin-bottom: 3px; }
.text { white-space: pre-wrap; word-break: break-word; color: var(--text-main); }
.degraded-tag {
  margin-left: 6px; font-size: 9.5px; color: #fbbf24;
  border: 1px solid rgba(251, 191, 36, 0.5); border-radius: 8px; padding: 0 5px;
}
.mock-badge {
  font-size: 10px; color: #fbbf24; border: 1px solid rgba(251, 191, 36, 0.5);
  background: rgba(251, 191, 36, 0.1); border-radius: 9px; padding: 1px 7px;
}
.live-badge {
  font-size: 10px; color: var(--green); border: 1px solid rgba(52, 211, 153, 0.5);
  background: rgba(52, 211, 153, 0.1); border-radius: 9px; padding: 1px 7px;
}
.typing i {
  display: inline-block; width: 5px; height: 5px; border-radius: 50%;
  background: var(--cyan); margin-right: 3px; animation: blink 1.1s infinite;
}
.typing i:nth-child(2) { animation-delay: 0.18s; }
.typing i:nth-child(3) { animation-delay: 0.36s; }
@keyframes blink { 0%, 100% { opacity: 0.25; } 50% { opacity: 1; } }
.compose { display: flex; gap: 8px; margin-top: 8px; }
.compose textarea { flex: 1; resize: none; }
.history {
  width: 232px;
  flex: 0 0 232px;
  border-left: 1px solid var(--line-soft);
  padding-left: 10px;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.history-head {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 12px; color: var(--text-sub); margin-bottom: 6px;
}
.history-list { list-style: none; margin: 0; padding: 0; overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 6px; }
.hitem {
  border: 1px solid var(--line-soft);
  border-radius: var(--radius-sm);
  padding: 6px 8px;
  cursor: pointer;
  background: rgba(9, 17, 31, 0.5);
}
.hitem:hover { border-color: var(--cyan); }
.hq { font-size: 12px; color: var(--text-main); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ha { font-size: 11px; color: var(--text-sub); margin: 2px 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hmeta { font-size: 9.5px; color: var(--text-faint); }
.sk-list { display: flex; flex-direction: column; gap: 6px; }
@media (max-width: 1100px) {
  .body { flex-direction: column; }
  .history { width: auto; flex: 0 0 auto; border-left: none; border-top: 1px solid var(--line-soft); padding: 8px 0 0; max-height: 180px; }
}
</style>
