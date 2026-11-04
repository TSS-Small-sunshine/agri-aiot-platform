<template>
  <div class="panel pg">
    <div class="panel-title">
      <span class="t-left"><span class="bar"></span>地块 2.5D 总览</span>
      <span class="sub">{{ plots.length }} 个地块 · 点击触发推演</span>
    </div>

    <div v-if="loading" class="pg-stage">
      <div class="skeleton sk-tile" v-for="i in 2" :key="i"></div>
    </div>

    <div v-else-if="error" class="err-inline">{{ error }}</div>

    <div v-else-if="!plots.length" class="empty">暂无地块数据</div>

    <!-- 提示语必须是 .pg-stage 的兄弟而非子元素：.pg-stage 是 row 方向的 flex 容器，
         提示语作为子项会按 flex-basis:auto 抢走约一半宽度，把舞台从 276px 压到 125px，
         地块卡只剩 60px 宽 —— 中文被省略号截断并相互重叠。 -->
    <template v-else>
      <div class="pg-stage">
        <!-- 纯 CSS 3D：perspective 提供景深，内层 rotateX(38deg) 把平面压成俯视地块。
             倾角不能太大：文字会被 cos(倾角) 垂直压缩，55deg 时只剩 0.57 倍高度，
             末行「12.5 亩 · 果实膨大期」看起来像被切掉一截。38deg 保留俯视透视，
             字形高度 14.2px（55deg 时仅 11px）。 -->
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
              <span class="tile-foot">
                <span class="dot" :class="plotOnline(p) ? 'online' : 'offline'"></span>
                <span class="nowrap">{{ onlineCount(p) }}/{{ deviceCount(p) }} 在线</span>
              </span>
              <span class="tile-meta mono nowrap">
                {{ p.area_mu != null ? p.area_mu + ' 亩' : '--' }}
                <template v-if="p.stage"> · {{ p.stage }}</template>
              </span>
            </button>
          </div>
        </div>
      </div>
      <p class="pg-hint">点击地块触发推演 · 拖动/缩放未开放</p>
    </template>
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
.pg-stage { flex: 1; display: flex; align-items: center; justify-content: center; padding: 4px 0; min-height: 0; }

/* 3D 舞台：占满 stage 全宽（不能留 flex 兄弟抢宽度） */
.pg-scene {
  flex: 1;
  min-width: 0;
  height: 100%;
  display: flex;
  align-items: center;
  perspective: 900px;
  perspective-origin: 50% 30%;
}
.pg-plane {
  flex: 1;
  height: 100%;
  display: grid;
  gap: 10px;
  transform: rotateX(38deg);
  transform-style: preserve-3d;
  transition: transform 0.35s ease;
}
.pg-scene:hover .pg-plane { transform: rotateX(34deg); }

.tile {
  position: relative;
  display: flex; flex-direction: column; gap: 0;
  min-height: 0;
  min-width: 0;
  padding: 7px 9px 11px;
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
.tile-code { font-size: 10px; line-height: 1.5; color: var(--v2-cyan); letter-spacing: 0.08em; }
.tile-name { font-size: 13px; line-height: 1.4; font-weight: 600; }
.tile-crop { font-size: 11px; line-height: 1.4; color: var(--v2-sub); }
.tile-foot { display: flex; align-items: center; gap: 4px; font-size: 10.5px; line-height: 1.5; color: var(--v2-sub); margin-top: auto; min-width: 0; }
.tile-meta { font-size: 10.5px; line-height: 1.5; color: var(--v2-sub); }

.sk-tile { min-height: 76px; }
.pg-hint { margin: 2px 0 0; font-size: 10.5px; color: var(--v2-sub); text-align: center; }
</style>
