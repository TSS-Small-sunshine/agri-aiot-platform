<template>
  <section class="panel plotmap">
    <header class="panel-title">
      <span class="t-left"><i class="bar"></i>地块点位示意图</span>
      <span class="sub mono">{{ layout.length }} 个地块 · {{ devices.length }} 台设备</span>
    </header>

    <p v-if="error" class="err-inline">{{ error }}</p>

    <p v-if="!devices.length" class="empty">暂无地块与设备数据</p>

    <svg v-else class="canvas" viewBox="0 0 420 210" preserveAspectRatio="xMidYMid meet">
      <defs>
        <linearGradient id="plotFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="rgba(52, 211, 153, 0.16)" />
          <stop offset="100%" stop-color="rgba(34, 211, 238, 0.05)" />
        </linearGradient>
        <filter id="glowDot" x="-80%" y="-80%" width="260%" height="260%">
          <feGaussianBlur stdDeviation="3" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>

      <g v-for="(p, pi) in layout" :key="p.plot_code">
        <rect
          :x="p.x" :y="p.y" :width="p.w" :height="p.h" rx="10"
          fill="url(#plotFill)"
          stroke="rgba(52, 211, 153, 0.4)" stroke-width="1"
          :class="{ 'plot-focus': focusPlot === p.plot_code }"
        />
        <text :x="p.x + 10" :y="p.y + 16" fill="#8aa6c4" font-size="11" font-weight="600">{{ p.plot_name }}</text>
        <text :x="p.x + p.w - 10" :y="p.y + 16" fill="#4b6584" font-size="9.5" text-anchor="end">
          {{ p.devices.length }} 台
        </text>

        <g v-for="(d, di) in p.devices" :key="d.device_code"
           class="node" :class="{ active: d.device_code === focusDevice }"
           @click="$emit('focus', d.device_code)">
          <circle
            :cx="nodeX(p, di)" :cy="p.y + p.h - 32" r="7"
            :fill="d.status === 'online' ? '#34d399' : '#f43f5e'"
            :opacity="d.status === 'online' ? 1 : 0.9"
            filter="url(#glowDot)"
          />
          <circle
            v-if="d.status === 'online'"
            :cx="nodeX(p, di)" :cy="p.y + p.h - 32" r="7"
            fill="none" stroke="#34d399" stroke-width="1" class="pulse"
          />
          <text :x="nodeX(p, di)" :y="p.y + p.h - 14" fill="#8aa6c4" font-size="9" text-anchor="middle">
            {{ d.device_code.split('-').pop() }} {{ d.type === 'soil' ? '墒情' : '环境' }}
          </text>
          <text :x="nodeX(p, di)" :y="p.y + p.h - 46" :fill="d.status === 'online' ? '#34d399' : '#f43f5e'" font-size="9" text-anchor="middle">
            {{ d.status === 'online' ? '在线' : '离线' }}
          </text>
        </g>
      </g>
    </svg>

    <div v-if="devices.length" class="legend">
      <span><i class="chip ok"></i>在线</span>
      <span><i class="chip bad"></i>离线</span>
      <span class="hint">点击点位可切换聚焦设备</span>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  devices: { type: Array, default: () => [] },
  meta: { type: Object, default: () => ({}) },
  focusDevice: { type: String, default: '' },
  error: { type: String, default: '' }
})
defineEmits(['focus'])

// 依据 /api/meta 的 plots 顺序与 /api/devices 的 plot_code 归组，动态排布地块
const layout = computed(() => {
  const byPlot = new Map()
  for (const d of props.devices) {
    if (!byPlot.has(d.plot_code)) byPlot.set(d.plot_code, [])
    byPlot.get(d.plot_code).push(d)
  }
  const metaPlots = Array.isArray(props.meta?.plots) ? props.meta.plots : []
  const codes = metaPlots.length
    ? metaPlots.map((p) => p.plot_code).filter((c) => byPlot.has(c))
    : [...byPlot.keys()]

  const rowH = 92
  return codes.map((code, i) => {
    const meta = metaPlots.find((p) => p.plot_code === code)
    const devices = byPlot.get(code) || []
    return {
      plot_code: code,
      plot_name: meta?.plot_name || `${code} 区`,
      x: 14,
      y: 8 + i * rowH,
      w: 392,
      h: rowH - 14,
      devices
    }
  })
})

const focusPlot = computed(() => {
  const d = props.devices.find((x) => x.device_code === props.focusDevice)
  return d ? d.plot_code : ''
})

function nodeX(plot, index) {
  const count = plot.devices.length || 1
  const usable = plot.w - 90
  const step = count > 1 ? usable / (count - 1) : 0
  return count > 1 ? plot.x + 45 + index * step : plot.x + plot.w / 2
}
</script>

<style scoped>
.plotmap { display: flex; flex-direction: column; height: 100%; }
.canvas { width: 100%; flex: 1; min-height: 170px; }
.plot-focus { stroke: rgba(34, 211, 238, 0.85) !important; }
.node { cursor: pointer; }
.node:hover circle { stroke: #22d3ee; stroke-width: 1.5; }
.node.active circle { stroke: #22d3ee; stroke-width: 2; }
.pulse {
  transform-box: fill-box;
  transform-origin: center;
  animation: ping 2s ease-out infinite;
}
@keyframes ping {
  0% { transform: scale(1); opacity: 0.9; }
  70% { transform: scale(2.4); opacity: 0; }
  100% { transform: scale(2.4); opacity: 0; }
}
.legend { display: flex; align-items: center; gap: 12px; font-size: 10.5px; color: var(--text-faint); }
.chip { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
.chip.ok { background: var(--green); }
.chip.bad { background: var(--red); }
.hint { margin-left: auto; }
</style>
