// ECharts 按需引入：只注册用到的模块，避免全量 import 撑大产物体积
import * as echarts from 'echarts/core'
import { LineChart, GaugeChart, GraphChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  MarkLineComponent
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart,
  GaugeChart,
  GraphChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  MarkLineComponent,
  CanvasRenderer
])

// 统一的深色科技感基础配置
export const DARK_THEME = {
  textStyle: { color: '#8aa6c4', fontFamily: "'Microsoft YaHei', system-ui, sans-serif" },
  axisLine: { lineStyle: { color: 'rgba(56, 89, 133, 0.65)' } },
  splitLine: { lineStyle: { color: 'rgba(56, 89, 133, 0.22)', type: 'dashed' } },
  tooltip: {
    backgroundColor: 'rgba(9, 17, 31, 0.94)',
    borderColor: 'rgba(34, 211, 238, 0.45)',
    borderWidth: 1,
    textStyle: { color: '#e2f2ff', fontSize: 12 }
  }
}

// V1 大屏配色：/legacy 必须与 V1 视觉一致，故这组常量逐字冻结，不得改动
export const COLORS = {
  temperature: '#fbbf24',
  humidity: '#22d3ee',
  soil: '#34d399',
  red: '#f43f5e'
}

// V2 主题配色（V2_PLAN.md 第 10 节六色）。warn 黄为规范外补充：
// 第 7/10 节要求 severity=warn 用黄，但六色清单里没有黄色，故单列一项。
export const PALETTE = {
  bg: '#121212',
  cyan: '#00E5FF',
  green: '#00E676',
  red: '#FF3B30',
  warn: '#FFB300',
  text: '#E0E0E0',
  sub: '#8A8A8A'
}

// 推演节点 severity → 颜色（current 走青色，其余按 severity）
export const SEVERITY_COLOR = {
  current: PALETTE.cyan,
  high: PALETTE.red,
  warn: PALETTE.warn,
  good: PALETTE.green
}

export { echarts }
