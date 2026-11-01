// 全部可调参数集中在此，来源于 Vite 注入的环境变量（VITE_*），带安全默认值
const env = import.meta.env || {}

export const POLL_INTERVAL_MS = Number(env.VITE_POLL_INTERVAL_MS || 5000)
export const API_TIMEOUT_MS = Number(env.VITE_API_TIMEOUT_MS || 5000)
export const CHART_WINDOW_POINTS = Number(env.VITE_CHART_WINDOW_POINTS || 60)
export const HISTORY_HOURS = Number(env.VITE_HISTORY_HOURS || 1)
export const ALERT_LIMIT = Number(env.VITE_ALERT_LIMIT || 20)
export const AI_HISTORY_LIMIT = Number(env.VITE_AI_HISTORY_LIMIT || 20)
export const SUMMARY_HOURS = Number(env.VITE_SUMMARY_HOURS || 24)

