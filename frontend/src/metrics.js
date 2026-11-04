// 指标注册表：新增指标（如 co2）只需在此登记中文名、单位与配色，
// 指标卡 / 折线图 / 仪表 / 告警面板统一从这里取用，避免各处硬编码中文名。
export const METRIC_LABEL = {
  temperature: '温度',
  humidity: '湿度',
  soil_moisture: '土壤墒情',
  soil_temp: '土壤温度',
  co2: '二氧化碳浓度'
}

export const METRIC_UNIT = {
  temperature: '℃',
  humidity: '%',
  soil_moisture: '%',
  soil_temp: '℃',
  co2: 'ppm'
}

// 前三个指标刻意沿用 V1 冻结配色（echarts.js 的 COLORS），/legacy 的折线因此逐像素不变
export const METRIC_COLOR = {
  temperature: '#fbbf24',
  humidity: '#22d3ee',
  soil_moisture: '#34d399',
  soil_temp: '#FF7A59',
  co2: '#A78BFA'
}

// 地块未声明 metrics 时的兜底指标集
export const DEFAULT_METRICS = ['temperature', 'humidity', 'soil_moisture']

// CO₂ 阈值兜底：/api/meta 顶层 thresholds.co2 或地块 thresholds.co2 存在时用后端的；
// 否则用这一组内置值（400~1200 正常、>1500 预警），界面会标注「内置阈值」。
export const CO2_FALLBACK_THRESHOLDS = { min: 400, max: 1200, critical_min: 300, critical_max: 1500 }

export function metricLabel(metric) {
  return METRIC_LABEL[metric] || metric || '--'
}

export function metricUnit(metric) {
  return METRIC_UNIT[metric] || ''
}

// 地块生效阈值：优先地块自带 thresholds，其次 /api/meta 顶层 thresholds
export function plotThresholds(plot, globalThresholds) {
  const own = plot && plot.thresholds
  if (own && Object.keys(own).length) return own
  return globalThresholds || {}
}

export function metricThreshold(metric, plot, globalThresholds) {
  const th = plotThresholds(plot, globalThresholds)
  const own = th[metric]
  if (own && Object.keys(own).length) return own
  if (metric === 'co2') return CO2_FALLBACK_THRESHOLDS
  return {}
}

// 四档判定：critical_min / critical_max 之外为 high，min / max 之外为 warn
export function evaluateMetric(metric, value, thresholds) {
  if (value === null || value === undefined || value === '') return { level: 'unknown', text: '无数据' }
  const v = Number(value)
  if (Number.isNaN(v)) return { level: 'unknown', text: '无数据' }
  const t = thresholds || {}
  const { min, max, critical_min: cmin, critical_max: cmax } = t
  if (cmin !== undefined && cmin !== null && v < cmin) return { level: 'high', text: '严重偏低' }
  if (cmax !== undefined && cmax !== null && v > cmax) return { level: 'high', text: '严重偏高' }
  if (min !== undefined && min !== null && v < min) return { level: 'warn', text: '偏低' }
  if (max !== undefined && max !== null && v > max) return { level: 'warn', text: '偏高' }
  return { level: 'good', text: '正常' }
}

// 从 /api/telemetry/latest 的 items 里取某地块某指标的最新值（多设备取第一台有值的）
export function latestValue(items, plotCode, metric) {
  const list = items || []
  const hit = list.find((x) => x.plot_code === plotCode && x[metric] !== null && x[metric] !== undefined)
  return hit ? hit[metric] : null
}

// 汇总兜底：latest 无值时用 /api/telemetry/summary 的均值
export function valueWithSummary(items, plotCode, metric, summary) {
  const v = latestValue(items, plotCode, metric)
  if (v !== null) return v
  const avg = summary && summary[metric] ? summary[metric].avg : null
  return avg === undefined ? null : avg
}

export function fmt1(v) {
  return v === null || v === undefined || Number.isNaN(Number(v)) ? '--' : Number(v).toFixed(1)
}