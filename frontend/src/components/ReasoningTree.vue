<template>
  <div class="panel rt">
    <div class="panel-title">
      <span class="t-left">
        <span class="bar"></span>因果推演树
        <span v-if="result" class="sub">{{ result.context?.plot?.name || result.plot_code }} · {{ result.summary }}</span>
      </span>
      <span class="t-right">
        <span v-if="result" class="tag" :class="tag.kind">{{ tag.text }}</span>
        <button v-if="result" class="btn" type="button" @click="$emit('rerun')">重新推演</button>
      </span>
    </div>

    <!-- 推演中：骨架 -->
    <div v-if="loading" class="rt-loading">
      <div class="skeleton sk-graph"></div>
      <p class="rt-hint">推演中… 正在汇总地块指标、气象与阈值，最多等待 {{ Math.round(REASONING_TIMEOUT_MS / 1000) }}s</p>
    </div>

    <div v-else-if="error" class="rt-error">
      <p class="err-inline">{{ error }}</p>
      <button class="btn" type="button" @click="$emit('rerun')">重试</button>
    </div>

    <div v-else-if="!result" class="empty">点击左侧任一块地，开始一次因果推演</div>

    <div v-else class="rt-body">
      <div class="rt-metrics">
        <span class="m-item"><i class="m-k">减产风险</i><b class="mono m-v danger">{{ num(result.yield_loss_pct) }}%</b></span>
        <span class="m-item"><i class="m-k">预计耗电</i><b class="mono m-v warn">{{ num(result.power_kwh) }} 度</b></span>
        <span class="m-item"><i class="m-k">耗时</i><b class="mono m-v">{{ result.latency_ms }}ms</b></span>
        <span class="m-item"><i class="m-k">模型</i><b class="mono m-v nowrap">{{ result.model || '--' }}</b></span>
        <span class="m-item"><i class="m-k">推演编号</i><b class="mono m-v nowrap">{{ result.reasoning_id }}</b></span>
      </div>

      <div ref="chartEl" class="rt-chart"></div>

      <div v-if="planNodes.length" class="rt-plans">
        <div class="rt-plans-head">
          <span class="bar"></span>可执行干预方案（{{ planNodes.length }}）
          <span class="sub">点击节点或卡片执行；状态点由 /api/command/history 轮询驱动</span>
        </div>
        <div class="plan-list">
          <div
            v-for="n in planNodes"
            :key="n.id"
            class="plan-card"
            :class="{ active: n.id === activeNodeId }"
            @click="activeNodeId = n.id"
          >
            <div class="plan-head">
              <span class="dot good-dot"></span>
              <span class="plan-label">{{ n.label }}</span>
              <span class="tag green mono">{{ n.command?.action || '--' }}</span>
            </div>
            <p v-if="n.sub" class="plan-sub">{{ n.sub }}</p>
            <p v-if="n.command" class="plan-dev mono">
              目标设备 {{ n.command.device_code || '--' }} · 参数 {{ paramsText(n.command.params) }}
            </p>
            <p v-if="n.effect" class="plan-effect mono">
              <template v-if="n.effect.soil_moisture_delta != null">墒情回升 {{ num(n.effect.soil_moisture_delta) }}%</template>
              <template v-if="n.effect.yield_recover_pct != null"> · 挽回产量 {{ num(n.effect.yield_recover_pct) }}%</template>
            </p>
            <CommandButton
              v-if="n.command"
              :node="n"
              :plot-code="result.plot_code"
              :reasoning-id="result.reasoning_id"
              :record="cmdRecords[n.id] || null"
              @executed="onExecuted(n, $event)"
            />
            <SkuCard :keywords="n.sku_keywords || []" />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import CommandButton from './CommandButton.vue'
import SkuCard from './SkuCard.vue'
import { echarts, SEVERITY_COLOR, PALETTE } from '../echarts'
import { REASONING_TIMEOUT_MS } from '../config'
import { sourceTag } from '../sourceLabel'

const props = defineProps({
  result: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' }
})

const emit = defineEmits(['rerun', 'executed'])

const chartEl = ref(null)
const activeNodeId = ref('')
// node_id -> 该节点最近一次指令记录；重新推演会重建 CommandButton，靠它恢复状态点
const cmdRecords = ref({})
let chart = null
let ro = null

const tag = computed(() => sourceTag(props.result))
const planNodes = computed(() =>
  (props.result?.tree?.nodes || []).filter((n) => n.type === 'plan' && n.command)
)

const num = (v) => (v === null || v === undefined ? '--' : Number(v).toFixed(1))

function paramsText(params) {
  if (!params || typeof params !== 'object') return '--'
  const parts = Object.entries(params).map(([k, v]) => `${k}=${v}`)
  return parts.length ? parts.join(', ') : '--'
}

function onExecuted(node, res) {
  if (node?.id && res?.command_id) cmdRecords.value = { ...cmdRecords.value, [node.id]: res }
  emit('executed', { node, res })
}

// 画布内边距（px）。布局与 series 的 left/right/top/bottom 用同一个值，
// 使 view 坐标系的包围盒与 viewRect 完全重合 → 变换恒为 1:1，节点既不被裁也不被拉伸。
// 取 18 而不是更小，是为了给 shadowBlur 16 的节点辉光留出余量。
const PAD = 18

// 画布实际像素尺寸：布局以它为准，所以 resize 时必须重算布局（不能只 chart.resize()）
function chartBox() {
  const el = chartEl.value
  return {
    w: Math.max(240, Math.round(el?.clientWidth || 900)),
    h: Math.max(140, Math.round(el?.clientHeight || 250))
  }
}

// 按容器像素手工分层布局：x 按 level 递增、y 同层均分，
// 并保证「最左节点左边界 = PAD」「最右节点右边界 = W - PAD」「上下同理」，
// 于是撑边节点（见 padNode）定义的包围盒与 series 内边距严格重合，得到 1:1 变换。
function buildLayout(nodes, W, H) {
  const pos = new Map()
  if (!nodes.length) return pos
  const byLevel = new Map()
  for (const n of nodes) {
    const lv = Number(n.level || 0)
    if (!byLevel.has(lv)) byLevel.set(lv, [])
    byLevel.get(lv).push(n)
  }
  const levels = [...byLevel.entries()].sort((a, b) => a[0] - b[0])
  const widths = levels.map(([, list]) => Math.max(...list.map((n) => nodeSize(n)[0])))
  const heights = levels.map(([, list]) => Math.max(...list.map((n) => nodeSize(n)[1])))
  const ch = H - PAD * 2
  const last = levels.length - 1
  levels.forEach(([, list], li) => {
    const x0 = PAD + widths[0] / 2
    const x1 = W - PAD - widths[last] / 2
    const x = last === 0 ? W / 2 : x0 + ((x1 - x0) * li) / last
    const m = list.length
    const maxH = heights[li]
    // 同层多节点时纵向均分，且总跨度不超过可用高度，避免上下溢出
    const step = m > 1 ? Math.min(maxH + 26, Math.max(0, ch - maxH) / (m - 1)) : 0
    const top = H / 2 - ((m - 1) * step) / 2
    list.forEach((n, i) => pos.set(n.id, { x, y: m === 1 ? H / 2 : top + i * step }))
  })
  return pos
}

// 撑边节点用的包围盒四角：与 series 的像素内边距严格一致
function seriesRange(W, H) {
  return { xMin: PAD, xMax: W - PAD, yMin: PAD, yMax: H - PAD }
}

// 零尺寸撑边节点：只为把 view 坐标系的包围盒撑到真实节点矩形的外沿，
// 自身不可见（symbolSize 0 + opacity 0）、无标签、不参与 tooltip。
function padNode(x, y) {
  return {
    id: `__pad_${x}_${y}`,
    name: '',
    x,
    y,
    symbolSize: 0,
    raw: { type: 'pad', label: '', sub: '', severity: 'good', level: 0 },
    itemStyle: { opacity: 0 },
    label: { show: false }
  }
}

// 节点矩形必须真正包住文字：ECharts graph 的自动适配只按 symbolSize 计算包围盒，
// 文字一旦溢出矩形，处在最左/最右的节点就会被画布边缘裁掉。
// 因此宽度不按字数估算，而是用 canvas measureText 量真实文本宽度
// （字体与 series.label.rich 的 t/s 保持一致：600 11.5px / 10px sans-serif）。
const LABEL_FONT = '600 11.5px sans-serif'
const SUB_FONT = '10px sans-serif'
const NODE_PAD_X = 24
const NODE_MIN_W = 120
const NODE_MAX_W = 560
let measureCtx = null

function textWidth(text, font) {
  if (!text) return 0
  if (!measureCtx) measureCtx = document.createElement('canvas').getContext('2d')
  measureCtx.font = font
  return measureCtx.measureText(String(text)).width
}

function nodeSize(n) {
  const labelW = textWidth(n.label, LABEL_FONT)
  const subW = textWidth(n.sub, SUB_FONT)
  const w = Math.min(NODE_MAX_W, Math.max(NODE_MIN_W, Math.ceil(Math.max(labelW, subW)) + NODE_PAD_X))
  const h = n.sub ? 50 : 34
  return [w, h]
}

function buildOption() {
  const res = props.result
  const nodes = res?.tree?.nodes || []
  const links = res?.tree?.links || []
  const box = chartBox()
  const pos = buildLayout(nodes, box.w, box.h)
  const range = seriesRange(box.w, box.h)

  return {
    backgroundColor: 'transparent',
    tooltip: {
      backgroundColor: 'rgba(18,18,18,0.96)',
      borderColor: 'rgba(0,229,255,0.45)',
      textStyle: { color: PALETTE.text, fontSize: 12 },
      formatter: (p) => {
        if (p.dataType === 'edge') return ''
        const n = p.data.raw || {}
        if (n.type === 'pad') return ''
        const lines = [`<b>${n.label || ''}</b>`]
        if (n.sub) lines.push(n.sub)
        lines.push(`severity: ${n.severity} · type: ${n.type} · level: ${n.level}`)
        if (n.command) lines.push(`指令: ${n.command.action}`)
        return lines.join('<br/>')
      }
    },
    series: [
      {
        type: 'graph',
        layout: 'none',
        roam: true,
        draggable: true,
        symbol: 'roundRect',
        // 根因：ECharts 的 view 坐标系只用节点「中心点」算包围盒
        // （echarts/lib/chart/graph/createView.js: bbox.fromPoints(positions)），
        // 完全不含 symbolSize，因此任何百分比内边距都挡不住 symbol/文字溢出画布。
        // 修法：用两个零尺寸「撑边节点」把包围盒撑到真实节点矩形的外沿（见 data 尾部），
        // 再用像素级内边距（数字即 px）留出安全边。
        left: PAD, right: PAD, top: PAD, bottom: PAD,
        label: {
          show: true,
          color: PALETTE.text,
          fontSize: 11.5,
          lineHeight: 15,
          formatter: (p) => {
            const n = p.data.raw || {}
            return n.sub ? `{t|${n.label}}\n{s|${n.sub}}` : `{t|${n.label}}`
          },
          rich: {
            t: { color: PALETTE.text, fontSize: 11.5, fontWeight: 600, lineHeight: 15 },
            s: { color: PALETTE.sub, fontSize: 10, lineHeight: 13 }
          }
        },
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: 7,
        lineStyle: { color: 'rgba(0,229,255,0.42)', width: 1.2, curveness: 0.22, opacity: 0.9 },
        emphasis: { focus: 'adjacency', lineStyle: { width: 2, color: PALETTE.cyan } },
        data: nodes.map((n) => {
          const p = pos.get(n.id) || { x: 0, y: 0 }
          const color = SEVERITY_COLOR[n.severity] || SEVERITY_COLOR.good
          return {
            id: n.id,
            name: n.label,
            x: p.x,
            y: p.y,
            symbolSize: nodeSize(n),
            raw: n,
            itemStyle: {
              color: 'rgba(18,18,18,0.92)',
              borderColor: color,
              borderWidth: n.type === 'current' ? 1.6 : 1.2,
              // 节点发光：规范要求的 shadowBlur 动效
              shadowBlur: n.severity === 'high' ? 16 : 10,
              shadowColor: color
            },
            label: { color: PALETTE.text }
          }
        }).concat([
          // 对角两点即可把包围盒撑到 [range.xMin, range.xMax] × [range.yMin, range.yMax]
          padNode(range.xMin, range.yMin),
          padNode(range.xMax, range.yMax)
        ]),
        links: links.map((l) => ({ source: l.source, target: l.target }))
      }
    ]
  }
}

// 销毁实例：.rt-chart 会被 v-if 卸载（loading 分支会替换掉整个 .rt-body），
// 旧实例若继续持有游离容器，后续 setOption 就画在 DOM 之外，画布永久空白。
function teardown() {
  if (ro) { ro.disconnect(); ro = null }
  if (chart) { chart.dispose(); chart = null }
}

function render() {
  if (!props.result || props.loading) {
    teardown()
    return
  }
  nextTick(() => {
    if (!chartEl.value) return
    // 容器可能已被卸载重挂载：实例的宿主不是当前 DOM 节点时必须重建
    if (chart && chart.getDom() !== chartEl.value) teardown()
    if (!chart) chart = echarts.init(chartEl.value, null, { renderer: 'canvas' })
    if (!ro) {
      // 布局按容器像素算，尺寸变化必须重算布局，只 resize 会留下旧的节点坐标
      ro = new ResizeObserver(() => {
        if (!chart || !chartEl.value) return
        // 容器被 display:none 隐藏（大字模式）时 clientWidth/Height 为 0：
        // 此时 resize 会把画布压成 100×0 并丢掉布局，直接跳过、保留最后一张有效画布。
        // 恢复显示时 RO 会再触发一次，届时按真实尺寸重建。
        if (!chartEl.value.clientWidth || !chartEl.value.clientHeight) return
        chart.resize()
        chart.setOption(buildOption(), true)
      })
      ro.observe(chartEl.value)
    }
    chart.setOption(buildOption(), true)
  })
}

watch(() => [props.result, props.loading], render, { immediate: true, deep: false })

onBeforeUnmount(teardown)
</script>

<style scoped>
.rt { display: flex; flex-direction: column; min-height: 340px; }
.t-right { display: flex; align-items: center; gap: 8px; }
.rt-body { flex: 1; display: flex; flex-direction: column; gap: 6px; min-height: 0; }

.rt-metrics { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 10.5px; color: var(--v2-sub); }
.m-item { display: inline-flex; align-items: baseline; gap: 5px; }
.m-k { font-style: normal; color: var(--v2-sub); }
.m-v { font-size: 12px; color: var(--v2-text); max-width: 150px; }
.m-v.danger { color: var(--v2-red); }
.m-v.warn { color: var(--v2-warn); }

.rt-chart { flex: 1; min-height: 250px; width: 100%; }

.rt-loading { flex: 1; display: flex; flex-direction: column; gap: 8px; }
.sk-graph { flex: 1; min-height: 230px; }
.rt-hint { margin: 0; font-size: 10.5px; color: var(--v2-sub); text-align: center; }
.rt-error { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; }

.rt-plans { border-top: 1px dashed var(--v2-line-soft); padding-top: 6px; }
.rt-plans-head { display: flex; align-items: center; gap: 7px; font-size: 11px; color: var(--v2-green); margin-bottom: 6px; }
.rt-plans-head .bar { width: 2px; height: 11px; background: var(--v2-green); border-radius: 1px; }
.rt-plans-head .sub { font-size: 10px; color: var(--v2-sub); }
.plan-list { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; }
.plan-card {
  flex: 0 0 262px;
  border: 1px solid rgba(0, 230, 118, 0.35);
  border-radius: var(--v2-r-sm);
  background: rgba(0, 230, 118, 0.05);
  padding: 7px 9px;
  transition: box-shadow 0.18s, border-color 0.18s;
}
.plan-card.active { border-color: var(--v2-green); box-shadow: 0 0 14px rgba(0, 230, 118, 0.28); }
.plan-head { display: flex; align-items: center; gap: 6px; }
.good-dot { background: var(--v2-green); box-shadow: 0 0 7px var(--v2-green); }
.plan-label { flex: 1; font-size: 12px; font-weight: 600; color: var(--v2-text); }
.plan-sub { margin: 3px 0 0; font-size: 10.5px; color: var(--v2-sub); }
.plan-dev, .plan-effect { margin: 3px 0 0; font-size: 10px; color: var(--v2-sub); }
</style>
