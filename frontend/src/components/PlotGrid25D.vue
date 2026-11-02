<template>
  <div class="panel pg">
    <div class="panel-title">
      <span class="t-left"><span class="bar"></span>地块 2.5D 总览</span>
      <span class="sub">{{ plots.length }} 个地块 · 点击地块触发推演</span>
    </div>

    <div v-if="loading" class="pg-stage">
      <div class="skeleton sk-tile" v-for="i in 2" :key="i"></div>
    </div>

    <div v-else-if="error" class="err-inline">{{ error }}</div>

    <div v-else-if="!plots.length" class="empty">暂无地块数据</div>

    <div v-else class="pg-stage">
      <!-- 纯 CSS 3D：perspective 提供景深，内层 rotateX(55deg) 把平面压成俯视地块 -->
      <div class="pg-scene">
        <div class="pg-plane" :style="planeStyle">
          <button
            v-for="p in plots"
            :key="p.plot_code"
            class="tile"
            :class="{ active: p.plot_code === selected, alert: plotLevel(p) === 'high' }"
            :style="tileStyle(p)"
            type="button"
            @click="select(p)"
          >
            <span class="tile-code mono">{{ p.plot_code }}</span>
            <span class="tile-name nowrap">{{ p.name || p.plot_name }}</span>
            <span class="tile-crop nowrap">{{ p.crop || '--' }}</span>
            <span class="tile-foot mono">
              <span class="dot" :class="plotOnline(p) ? 'online' : 'offline'"></span>
              {{ onlineCount(p) }}/{{ deviceCount(p) }} 在线
            </span>
            <span class="tile-area mono">{{ p.area_mu != null ? p.area_mu + ' 亩' : '--' }}</span>
            <span class="tile-stage nowrap">{{ p.stage || '' }}</span>
          </button>
        </div>
      </div>
      <p class="pg-hint">拖动/缩放未开放；点击地块即在右侧因果树推演该地块的当前态势。</p>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  plots: { type: Array, default: () => [] },
  devices: { type: Array, default: () => [] },
  selected: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
  // 各地块最新指标（来自 /api/telemetry/latest 聚合），用于地块着色
  levels: { type: Object, default: () => ({}) }
})

const emit = defineEmits(['select'])

const cols = computed(() => Math.max(1, ...props.plots.map((p) => Number(p.col ?? 0) + 1)))
const rows = computed(() => Math.max(1, ...props.plots.map((p) => Number(p.row ?? 0) + 1)))

const planeStyle = computed(() => ({
  gridTemplateColumns: `repeat(${cols.value}, minmax(0, 1fr))`,
  gridTemplateRows: `repeat(${rows.value}, minmax(0, 1fr))`
}))

function tileStyle(p) {
  return {
    gridColumn: Number(p.col ?? 0) + 1,
    gridRow: Number(p.row ?? 0) + 1
  }
}

const deviceCount = (p) => (p.devices || []).length
const onlineCount = (p) => (p.devices || []).filter((c) => isOnline(c)).length
const plotOnline = (p) => onlineCount(p) > 0

function isOnline(code) {
  const d = props.devices.find((x) => x.device_code === code)
  return d ? d.status === 'online' : false
}

const plotLevel = (p) => props.levels[p.plot_code] || 'good'

function select(p) {
  emit('select', p)
}
</script>

<style scoped>
.pg { display: flex; flex-direction: column; min-height: 260px; }
.pg-stage { flex: 1; display: flex; align-items: center; justify-content: center; padding: 6px 2px; }

/* 3D 舞台 */
.pg-scene {
  width: 100%;
  perspective: 900px;
  perspective-origin: 50% 30%;
}
.pg-plane {
  display: grid;
  gap: 12px;
  transform: rotateX(55deg);
  transform-style: preserve-3d;
  transition: transform 0.35s ease;
}
.pg-scene:hover .pg-plane { transform: rotateX(50deg); }

.tile {
  position: relative;
  display: flex; flex-direction: column; gap: 1px;
  min-height: 76px;
  padding: 7px 9px;
  text-align: left;
  font-family: inherit;
  color: var(--v2-text);
  background: rgba(255, 255, 255, 0.035);
  border: var(--v2-line);
  border-radius: var(--v2-r-sm);
  cursor: pointer;
  transform: translateZ(0);
  transition: transform 0.2s ease, box-shadow 0.2s ease, background 0.2s ease, border-color 0.2s ease;
}
/* hover 发光并抬起：translateZ 在 3D 平面内表现为向上浮起 */
.tile:hover {
  background: rgba(0, 229, 255, 0.09);
  border-color: var(--v2-cyan);
  box-shadow: 0 0 0 1px var(--v2-cyan), 0 0 18px rgba(0, 229, 255, 0.4);
  transform: translateZ(16px);
}
.tile.active {
  background: rgba(0, 229, 255, 0.14);
  border-color: var(--v2-cyan);
  box-shadow: 0 0 0 1px var(--v2-cyan), 0 0 22px rgba(0, 229, 255, 0.45);
}
.tile.alert { border-color: rgba(255, 59, 48, 0.6); }
.tile.alert::after {
  content: ''; position: absolute; right: 6px; top: 6px;
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--v2-red); box-shadow: 0 0 8px var(--v2-red);
  animation: v2-breathe-red 1.4s ease-in-out infinite;
}
.tile-code { font-size: 10px; color: var(--v2-cyan); letter-spacing: 0.1em; }
.tile-name { font-size: 12.5px; font-weight: 600; }
.tile-crop { font-size: 10.5px; color: var(--v2-sub); }
.tile-foot { display: flex; align-items: center; gap: 4px; font-size: 10px; color: var(--v2-sub); margin-top: auto; }
.tile-area { font-size: 10px; color: var(--v2-sub); }
.tile-stage { font-size: 10px; color: var(--v2-sub); }

.sk-tile { min-height: 76px; }
.pg-hint { margin: 4px 0 0; font-size: 10.5px; color: var(--v2-sub); text-align: center; }
</style>
