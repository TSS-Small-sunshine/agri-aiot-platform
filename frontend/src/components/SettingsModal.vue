<template>
  <div v-if="open" class="modal-mask" @click.self="close">
    <div class="modal panel" role="dialog" aria-modal="true" aria-label="模型与接口设置">
      <div class="panel-title">
        <span class="t-left"><span class="bar"></span>模型与接口设置</span>
        <button class="btn" type="button" @click="close">关闭</button>
      </div>

      <div v-if="loading" class="sk-wrap">
        <div class="skeleton sk-row"></div>
        <div class="skeleton sk-row"></div>
        <div class="skeleton sk-row"></div>
      </div>

      <form v-else class="form" @submit.prevent="save">
        <label class="field">
          <span class="f-label">Base URL</span>
          <input v-model.trim="form.base_url" type="text" placeholder="https://api.openai.com/v1" spellcheck="false" />
          <span class="f-hint">OpenAI 兼容接口地址；留空表示沿用后端环境变量。</span>
        </label>

        <label class="field">
          <span class="f-label">API Key</span>
          <input
            v-model="form.api_key"
            type="password"
            :placeholder="keyPlaceholder"
            spellcheck="false"
            autocomplete="off"
            @focus="keyTouched = true"
          />
          <span class="f-hint">
            当前已保存：<span class="mono">{{ cfg.api_key_masked || '未配置' }}</span>
            <template v-if="!keyTouched"> · 不修改请留空</template>
          </span>
        </label>

        <div class="field">
          <span class="f-label">模型</span>
          <div ref="comboEl" class="combo">
            <input
              v-model.trim="modelQuery"
              class="combo-input"
              type="text"
              spellcheck="false"
              autocomplete="off"
              :placeholder="comboPlaceholder"
              @focus="onComboFocus"
              @input="onComboInput"
              @keydown.down.prevent="move(1)"
              @keydown.up.prevent="move(-1)"
              @keydown.enter.prevent="pickHighlighted"
              @keydown.esc="comboOpen = false"
            />
            <button v-if="form.model" class="combo-clear" type="button" title="恢复默认模型" @click="clearModel">×</button>
            <div v-if="comboOpen" class="combo-list" role="listbox">
              <div class="combo-item" :class="{ active: hl === 0, sel: !form.model }" @mousedown.prevent="pick('')">
                <span class="ci-id">（不指定模型 · 后端回落 mock-agronomist，真实端点会失败并降级）</span>
                <span v-if="!form.model" class="ci-tag">当前</span>
              </div>
              <div
                v-for="(m, i) in filteredModels"
                :key="m.id"
                class="combo-item"
                :class="{ active: hl === i + 1, sel: m.id === form.model }"
                @mousedown.prevent="pick(m.id)"
              >
                <span class="ci-id">{{ m.id }}</span>
                <span v-if="isEmbedding(m.id)" class="ci-tag">向量模型</span>
              </div>
              <div v-if="!filteredModels.length" class="combo-empty">没有匹配的模型，换个关键字试试</div>
            </div>
          </div>
          <span class="f-hint">
            共 {{ models.length }} 个模型，输入关键字过滤；当前：
            <span class="mono">{{ form.model || '（未指定）' }}</span>。保存后立即热生效。
          </span>
        </div>

        <p v-if="err" class="err-inline">{{ err }}</p>
        <p v-if="okMsg" class="ok-line">{{ okMsg }}</p>
        <p v-if="testMsg" class="test-line" :class="testOk ? 'pass' : 'fail'">{{ testMsg }}</p>

        <div class="actions">
          <button class="btn primary" type="submit" :disabled="saving">{{ saving ? '保存中…' : '保存' }}</button>
          <button class="btn" type="button" :disabled="testing" @click="test">{{ testing ? '测试中…' : '测试连接' }}</button>
          <span class="src mono">来源 {{ cfg.source || '--' }} · {{ cfg.path || '--' }}</span>
        </div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { getConfig, getModels, putConfig, testConfig } from '../api'

const props = defineProps({ open: { type: Boolean, default: false } })
const emit = defineEmits(['close', 'saved'])

const cfg = ref({})
const models = ref([])
const form = reactive({ base_url: '', api_key: '', model: '' })
// 模型选择器：接口可能返回两百多个模型，原生 <select> 无法检索、在 Electron 内嵌浏览器里
// 弹层还可能不渲染，故改为「可输入过滤 + 键盘可选」的组合框。
const modelQuery = ref('')
const comboOpen = ref(false)
const hl = ref(0)
const comboEl = ref(null)
const keyTouched = ref(false)
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const err = ref('')
const okMsg = ref('')
const testMsg = ref('')
const testOk = ref(false)

const keyPlaceholder = computed(() => (cfg.value.configured ? '已配置（留空即保持不变）' : '未配置，可粘贴明文 Key'))

async function load() {
  loading.value = true
  err.value = ''
  try {
    const [c, m] = await Promise.all([getConfig(), getModels().catch(() => ({ items: [] }))])
    cfg.value = c || {}
    models.value = m?.items || []
    // 关键：api_key 只以掩码回显，绝不写进表单，避免把掩码当明文回存
    form.base_url = c?.base_url || ''
    form.api_key = ''
    // 已配置 Key 却没选模型时，后端默认模型 id 是 mock-agronomist —— 拿它去调真实端点必然失败并降级。
    // 因此这里预选一个真实模型，让「不选」不再等于「必然降级」；用户仍可改或点 × 回到默认。
    form.model = c?.model || (c?.configured ? firstChatModel(m?.items || []) : '')
    modelQuery.value = form.model
    comboOpen.value = false
    hl.value = 0
    keyTouched.value = false
  } catch (e) {
    err.value = `读取配置失败：${e.message}`
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  err.value = ''
  okMsg.value = ''
  try {
    // api_key 三态：空串=保持不变（后端语义），因此未改动时不发送该键
    const payload = { base_url: form.base_url, model: form.model }
    if (form.api_key !== '') payload.api_key = form.api_key
    const c = await putConfig(payload)
    cfg.value = c || {}
    form.api_key = ''
    keyTouched.value = false
    okMsg.value = `已保存 · 当前模型 ${c?.model || '（默认）'}`
    emit('saved', c)
  } catch (e) {
    err.value = `保存失败：${e.message}`
  } finally {
    saving.value = false
  }
}

async function test() {
  testing.value = true
  testMsg.value = ''
  try {
    const r = await testConfig()
    // 「列表拉得到」不等于「所选模型调得通」：中转网关会列出已被上游下线的模型。
    const listOk = !!r.ok
    const modelChecked = r.model_ok !== null && r.model_ok !== undefined
    testOk.value = listOk && (r.model_ok !== false)
    if (!listOk) {
      testMsg.value = `连接失败：${r.error || '未知错误'}`
    } else if (modelChecked && r.model_ok === false) {
      testMsg.value = `接口连通（${r.latency_ms}ms · ${(r.models || []).length} 个模型），但所选模型 ${r.tested_model} 调用失败：${r.model_error || '未知原因'} —— 请换一个模型再保存`
    } else if (modelChecked) {
      testMsg.value = `连接成功 · ${r.latency_ms}ms · 发现 ${(r.models || []).length} 个模型 · 所选模型 ${r.tested_model} 可调用`
    } else {
      testMsg.value = `连接成功 · ${r.latency_ms}ms · 发现 ${(r.models || []).length} 个模型（尚未指定模型，未做调用验证）`
    }
  } catch (e) {
    testOk.value = false
    testMsg.value = `测试请求失败：${e.message}`
  } finally {
    testing.value = false
  }
}

// 向量/重排类模型不能用于对话，排在列表末尾并打标，但不隐藏（用户仍可选）
const NON_CHAT_RE = /(^|[\/_.-])(bge|m3|gte|embedding|embed|rerank|reranker|text-similarity)([\/_.-]|$)/i
const isEmbedding = (id) => NON_CHAT_RE.test(String(id || ''))

const comboPlaceholder = computed(() =>
  models.value.length ? `共 ${models.value.length} 个模型，输入关键字过滤` : '（使用默认模型）'
)

const filteredModels = computed(() => {
  const q = modelQuery.value.trim().toLowerCase()
  const sel = String(form.model || '').toLowerCase()
  // 输入框里就是当前选中项时，不把它当过滤条件，否则列表会被过滤成一条
  const list = !q || q === sel
    ? models.value
    : models.value.filter((m) => {
        const id = String(m.id || '').toLowerCase()
        const label = String(m.label || '').toLowerCase()
        return id.includes(q) || label.includes(q)
      })
  return [...list].sort((a, b) => (isEmbedding(a.id) ? 1 : 0) - (isEmbedding(b.id) ? 1 : 0))
})

function firstChatModel(list) {
  const usable = list.find((m) => !isEmbedding(m.id))
  return usable ? usable.id : ''
}

function pick(id) {
  form.model = id || ''
  modelQuery.value = form.model
  comboOpen.value = false
  hl.value = 0
}

function clearModel() {
  pick('')
}

// 聚焦时全选已填内容：否则输入框里已有模型名（预选值），用户直接打字会变成
// 「deepseek-v4.1-flashdeepseek」这种拼接串，过滤结果为空，看起来像坏了。
function onComboFocus(e) {
  comboOpen.value = true
  const el = e?.target
  if (el && typeof el.select === 'function') el.select()
}

function onComboInput(e) {
  const q = String(e?.target?.value ?? modelQuery.value ?? '').trim()
  modelQuery.value = q
  comboOpen.value = true
  hl.value = 0
  // 只有输入内容与某个模型 id 完全一致时才算选中；否则视为「正在过滤」，
  // 把当前选择退回默认，避免出现「输入框写着 A、实际保存的是 B」。
  const hit = models.value.find((m) => m.id === q)
  form.model = hit ? hit.id : ''
}

function move(delta) {
  const total = filteredModels.value.length + 1
  comboOpen.value = true
  hl.value = (hl.value + delta + total) % total
}

function pickHighlighted() {
  if (hl.value === 0) return pick('')
  const m = filteredModels.value[hl.value - 1]
  if (m) pick(m.id)
}

function onDocMouseDown(e) {
  if (comboEl.value && !comboEl.value.contains(e.target)) comboOpen.value = false
}

onMounted(() => document.addEventListener('mousedown', onDocMouseDown))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocMouseDown))

function close() {
  comboOpen.value = false
  emit('close')
}

watch(() => props.open, (v) => { if (v) load() })
</script>

<style scoped>
.modal-mask {
  position: fixed; inset: 0; z-index: 90;
  background: rgba(0, 0, 0, 0.66);
  display: flex; align-items: center; justify-content: center;
  padding: 20px;
}
.modal { width: 100%; max-width: 520px; padding: 14px 16px; background: #171717; border: var(--v2-line); }
.form { display: flex; flex-direction: column; gap: 11px; }
.field { display: flex; flex-direction: column; gap: 4px; }
.f-label { font-size: 11px; letter-spacing: 0.06em; color: var(--v2-cyan); }
.f-hint { font-size: 10.5px; color: var(--v2-sub); }
.field input, .field select { width: 100%; }
.combo { position: relative; }
.combo-input { width: 100%; padding-right: 30px; }
.combo-clear {
  position: absolute; top: 50%; right: 6px; transform: translateY(-50%);
  width: 20px; height: 20px; padding: 0; line-height: 1;
  font-size: 14px; color: var(--v2-sub); cursor: pointer;
  background: transparent; border: 0;
}
.combo-clear:hover { color: var(--v2-cyan); }
.combo-list {
  position: absolute; top: calc(100% + 4px); left: 0; right: 0; z-index: 5;
  max-height: 232px; overflow-y: auto;
  background: #101418; border: 1px solid rgba(0, 229, 255, 0.34); border-radius: 6px;
  box-shadow: 0 10px 26px rgba(0, 0, 0, 0.55);
}
.combo-item {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 10px; font-size: 12px; color: #cfe9f2; cursor: pointer;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}
.combo-item:last-child { border-bottom: 0; }
.combo-item.active { background: rgba(0, 229, 255, 0.14); }
.combo-item.sel { color: var(--v2-cyan); font-weight: 600; }
.ci-id { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ci-tag {
  flex: 0 0 auto; font-size: 10px; padding: 1px 6px; border-radius: 999px;
  color: #ffca7a; background: rgba(255, 176, 32, 0.14); border: 1px solid rgba(255, 176, 32, 0.34);
}
.combo-empty { padding: 10px; font-size: 11.5px; color: var(--v2-sub); }
.sk-wrap { display: flex; flex-direction: column; gap: 11px; }
.sk-row { height: 46px; }
.actions { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; margin-top: 3px; }
.src { font-size: 10px; color: var(--v2-sub); margin-left: auto; }
.ok-line { margin: 0; font-size: 11.5px; color: var(--v2-green); }
.test-line { margin: 0; font-size: 11.5px; }
.test-line.pass { color: var(--v2-green); }
.test-line.fail { color: var(--v2-red); }
</style>
