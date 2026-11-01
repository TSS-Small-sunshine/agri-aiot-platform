// ECharts 按需引入：只注册用到的模块，避免全量 import 撑大产物体积
import * as echarts from 'echarts/core'
import { LineChart, GaugeChart } from 'echarts/charts'
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

export const COLORS = {
  temperature: '#fbbf24',
  humidity: '#22d3ee',
  soil: '#34d399',
  red: '#f43f5e'
}

export { echarts }
