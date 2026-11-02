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

        <label class="field">
          <span class="f-label">模型</span>
          <select v-model="form.model">
            <option value="">（使用默认模型）</option>
            <option v-for="m in models" :key="m.id" :value="m.id">{{ m.label || m.id }}</option>
          </select>
          <span class="f-hint">下拉来自 GET /api/models；保存后立即热生效。</span>
        </label>

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
import { computed, reactive, ref, watch } from 'vue'
import { getConfig, getModels, putConfig, testConfig } from '../api'

const props = defineProps({ open: { type: Boolean, default: false } })
const emit = defineEmits(['close', 'saved'])

const cfg = ref({})
const models = ref([])
const form = reactive({ base_url: '', api_key: '', model: '' })
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
    form.model = c?.model || ''
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
    testOk.value = !!r.ok
    testMsg.value = r.ok
      ? `连接成功 · ${r.latency_ms}ms · 发现 ${(r.models || []).length} 个模型`
      : `连接失败：${r.error || '未知错误'}`
  } catch (e) {
    testOk.value = false
    testMsg.value = `测试请求失败：${e.message}`
  } finally {
    testing.value = false
  }
}

function close() {
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
.sk-wrap { display: flex; flex-direction: column; gap: 11px; }
.sk-row { height: 46px; }
.actions { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; margin-top: 3px; }
.src { font-size: 10px; color: var(--v2-sub); margin-left: auto; }
.ok-line { margin: 0; font-size: 11.5px; color: var(--v2-green); }
.test-line { margin: 0; font-size: 11.5px; }
.test-line.pass { color: var(--v2-green); }
.test-line.fail { color: var(--v2-red); }
</style>
