<template>
  <div v-if="items.length" class="sku-card">
    <div class="sku-head">
      <span class="sku-title">{{ showAll ? '农资商城' : '推荐农资' }}</span>
      <span class="sku-kw mono nowrap" :title="keywordText">{{ keywordText }}</span>
    </div>
    <ul class="sku-list">
      <li v-for="s in items" :key="s.id" class="sku-item">
        <div class="sku-img" :title="s.image || s.name">
          <span class="sku-img-mark mono">{{ (s.category || '农资').slice(0, 2) }}</span>
        </div>
        <div class="sku-mid">
          <div class="sku-name nowrap" :title="s.name">{{ s.name }}</div>
          <div class="sku-meta mono">
            <span class="sku-price">¥{{ price(s.price) }}</span>
            <span class="sku-unit">/{{ s.unit || '件' }}</span>
            <span v-if="s.stock !== null && s.stock !== undefined" class="sku-stock">库存 {{ s.stock }}</span>
          </div>
        </div>
        <button class="btn sku-add" :class="{ ok: added[s.id] }" type="button" @click="add(s)">
          {{ added[s.id] ? '已加入' : '加购' }}
        </button>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { getSkus } from '../api'
import { pushToast } from '../toast'

const props = defineProps({
  keywords: { type: Array, default: () => [] },
  // 右栏商城卡：不挂关键词时展示全部 SKU（GET /api/shop/skus 不带 keyword 即全量）
  showAll: { type: Boolean, default: false }
})

const items = ref([])
const added = ref({})

const keywordText = computed(() => (Array.isArray(props.keywords) ? props.keywords.join(' / ') : ''))

const price = (v) => (v === null || v === undefined ? '--' : Number(v).toFixed(2))

async function load() {
  const kws = (Array.isArray(props.keywords) ? props.keywords : []).filter(Boolean)
  // 无关键词且未开 showAll：该节点没有农资匹配，优雅隐藏（不渲染）
  if (!kws.length && !props.showAll) {
    items.value = []
    return
  }
  try {
    const queries = kws.length ? kws : ['']
    const results = await Promise.all(queries.map((k) => getSkus(k || undefined).catch(() => ({ items: [] }))))
    const byId = new Map()
    for (const res of results) {
      for (const it of res?.items || []) if (!byId.has(it.id)) byId.set(it.id, it)
    }
    items.value = [...byId.values()]
  } catch {
    // 商城不可用不是致命错误：优雅隐藏即可，不打扰主流程
    items.value = []
  }
}

function add(s) {
  added.value = { ...added.value, [s.id]: true }
  pushToast(`已加入采购清单：${s.name}`, { kind: 'ok' })
}

watch(() => [props.keywords, props.showAll], load, { deep: true, immediate: true })
</script>

<style scoped>
.sku-card {
  margin-top: 6px;
  border: var(--v2-line);
  border-radius: var(--v2-r-sm);
  background: rgba(0, 0, 0, 0.25);
  padding: 6px 7px;
}
.sku-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 5px; }
.sku-title { font-size: 10.5px; letter-spacing: 0.06em; color: var(--v2-green); }
.sku-kw { font-size: 10px; color: var(--v2-sub); max-width: 55%; }
.sku-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 5px; }
.sku-item { display: flex; align-items: center; gap: 7px; }
.sku-img {
  width: 30px; height: 30px; flex: 0 0 30px;
  border: 1px dashed rgba(0, 230, 118, 0.35);
  border-radius: var(--v2-r-sm);
  display: flex; align-items: center; justify-content: center;
  background: rgba(0, 230, 118, 0.06);
}
.sku-img-mark { font-size: 10px; color: var(--v2-green); }
.sku-mid { flex: 1; min-width: 0; }
.sku-name { font-size: 11.5px; color: var(--v2-text); }
.sku-meta { display: flex; align-items: baseline; gap: 6px; font-size: 10px; color: var(--v2-sub); }
.sku-price { color: var(--v2-warn); font-size: 11px; }
.sku-add { padding: 2px 7px; font-size: 11px; }
</style>
