import { API_TIMEOUT_MS } from './config'

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
