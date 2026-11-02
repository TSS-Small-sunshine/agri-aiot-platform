import { API_TIMEOUT_MS, REASONING_TIMEOUT_MS } from './config'

const BASE = import.meta.env?.VITE_API_BASE || '/api'

/** 统一的接口错误：保留 HTTP 状态码与后端 detail 文案 */
export class ApiError extends Error {
  constructor(message, status, url) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.url = url
  }
}

async function request(path, { method = 'GET', body, timeoutMs = API_TIMEOUT_MS } = {}) {
  const url = BASE + path
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(url, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal
    })
    const text = await res.text()
    let data = null
    if (text) {
      try {
        data = JSON.parse(text)
      } catch {
        data = null
      }
    }
    if (!res.ok) {
      const detail = data && typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`
      throw new ApiError(detail, res.status, url)
    }
    return data
  } catch (err) {
    if (err instanceof ApiError) throw err
    if (err && err.name === 'AbortError') {
      throw new ApiError(`请求超时（>${timeoutMs}ms）`, 0, url)
    }
    throw new ApiError(err?.message || '网络请求失败', 0, url)
  } finally {
    clearTimeout(timer)
  }
}

const qs = (params) => {
  const sp = new URLSearchParams()
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') sp.set(k, String(v))
  })
  const s = sp.toString()
  return s ? `?${s}` : ''
}

// ---------------- V1 接口（契约冻结，逐字段不得改）----------------
export const getHealth = () => request('/health')

export const getDevices = () => request('/devices')

export const getLatest = () => request('/telemetry/latest')

export const getHistory = (deviceCode, hours, limit) =>
  request(`/telemetry/history${qs({ device_code: deviceCode, hours, limit })}`)

export const getSummary = (hours) => request(`/telemetry/summary${qs({ hours })}`)

export const getAlerts = (limit, onlyUnacked) =>
  request(`/alerts${qs({ limit, only_unacked: onlyUnacked })}`)

export const ackAlert = (id) => request(`/alerts/${id}/ack`, { method: 'POST' })

export const getAiModels = () => request('/ai/models')

export const aiChat = (question, sessionId, model) =>
  request('/ai/chat', {
    method: 'POST',
    body: { question, session_id: sessionId, model }
  })

export const getAiHistory = (limit) => request(`/ai/history${qs({ limit })}`)

export const getMeta = () => request('/meta')

// ---------------- V2 新增接口（V2_PLAN.md 第 6 节 12 条）----------------
// 配置中心：GET 只回显掩码，PUT 热生效，POST /test 探活
export const getConfig = () => request('/config')

/**
 * 保存运行时配置。
 * api_key 语义（V2_PLAN.md 第 6 节）：键缺省=保持不变、空串=保持不变、null=清除。
 * 这里显式三态传递，绝不把掩码回写上去（掩码不是真 Key）。
 */
export const putConfig = (payload) =>
  request('/config', { method: 'PUT', body: payload, timeoutMs: REASONING_TIMEOUT_MS })

export const testConfig = () =>
  request('/config/test', { method: 'POST', timeoutMs: REASONING_TIMEOUT_MS })

export const getModels = () => request('/models')

// 推演：比对话慢，走独立超时
export const reasoningSimulate = (plotCode, nodeId) =>
  request('/reasoning/simulate', {
    method: 'POST',
    body: { plot_code: plotCode, node_id: nodeId ?? null },
    timeoutMs: REASONING_TIMEOUT_MS
  })

export const getReasoningHistory = (limit) => request(`/reasoning/history${qs({ limit })}`)

export const getReasoningDetail = (id) => request(`/reasoning/${encodeURIComponent(id)}`)

// 指令闭环
export const executeCommand = (payload) => request('/command/execute', { method: 'POST', body: payload })

export const getCommandHistory = (limit) => request(`/command/history${qs({ limit })}`)

// 气象与商城
export const getWeatherLatest = (plotCode) => request(`/weather/latest${qs({ plot_code: plotCode })}`)

export const getSkus = (keyword) => request(`/shop/skus${qs({ keyword })}`)
