<template>
  <div class="whitebox">
    <button class="wb-toggle" type="button" @click="open = !open">
      <span class="caret" :class="{ open }">▸</span>
      {{ open ? '收起推演逻辑' : '展开推演逻辑' }}
      <span v-if="steps.length" class="wb-count mono">{{ steps.length }} 步</span>
    </button>

    <ol v-if="open" class="wb-timeline">
      <li v-for="(s, i) in steps" :key="i" class="wb-step">
        <span class="wb-dot" :class="i === steps.length - 1 ? 'last' : ''"></span>
        <div class="wb-body">
          <div class="wb-head">
            <span class="wb-index mono">{{ String(i + 1).padStart(2, '0') }}</span>
            <span class="wb-step-name">{{ s.step }}</span>
            <span class="wb-ts mono">{{ fmtTs(s.ts) }}</span>
          </div>
          <p class="wb-detail">{{ s.detail }}</p>
        </div>
      </li>
    </ol>

    <p v-else-if="open" class="empty">本次没有白盒步骤</p>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  steps: { type: Array, default: () => [] }
})

const open = ref(false)
const steps = computed(() => (Array.isArray(props.steps) ? props.steps : []))

// ISO8601 带 +08:00 → 本地可读（不引 dayjs，手写格式化）
function fmtTs(ts) {
  if (!ts) return '--'
  const s = String(ts)
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/)
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6]}` : s
}
</script>

<style scoped>
.whitebox { margin-top: 6px; border-top: 1px dashed var(--v2-line-soft); padding-top: 5px; }

.wb-toggle {
  display: inline-flex; align-items: center; gap: 5px;
  font-family: inherit; font-size: 11px; color: var(--v2-cyan);
  background: none; border: none; padding: 1px 0; cursor: pointer;
}
.wb-toggle:hover { color: #5AF0FF; text-decoration: underline; }
.caret { display: inline-block; transition: transform 0.15s; font-size: 10px; }
.caret.open { transform: rotate(90deg); }
.wb-count { font-size: 10px; color: var(--v2-sub); }

.wb-timeline { list-style: none; margin: 8px 0 2px; padding: 0 0 0 3px; }
.wb-step { position: relative; padding: 0 0 10px 16px; }
.wb-step:last-child { padding-bottom: 2px; }
/* 时间轴竖线：用伪元素串起各步，最后一步不画线 */
.wb-step::before {
  content: ''; position: absolute; left: 4px; top: 10px; bottom: -2px;
  width: 1px; background: var(--v2-line-color);
}
.wb-step:last-child::before { display: none; }
.wb-dot {
  position: absolute; left: 0; top: 4px;
  width: 9px; height: 9px; border-radius: 50%;
  background: var(--v2-bg); border: 1px solid var(--v2-cyan);
  box-shadow: 0 0 5px rgba(0, 229, 255, 0.6);
}
.wb-dot.last { background: var(--v2-cyan); }

.wb-head { display: flex; align-items: baseline; gap: 7px; flex-wrap: wrap; }
.wb-index { font-size: 10px; color: var(--v2-sub); }
.wb-step-name { font-size: 12px; color: var(--v2-text); font-weight: 600; }
.wb-ts { font-size: 10px; color: var(--v2-sub); margin-left: auto; }
.wb-detail { margin: 3px 0 0; font-size: 11.5px; line-height: 1.6; color: var(--v2-sub); white-space: pre-wrap; word-break: break-word; }
</style>
