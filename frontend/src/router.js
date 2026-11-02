// 手写极简路由（V2_PLAN.md 第 10 节）：history.pushState + popstate 维护一个 reactive({path})。
// 只有 3 条路由，引入 vue-router 会多约 20KB 与一个依赖，违背「禁止臃肿依赖」硬约束。
import { reactive } from 'vue'
import { ROUTES } from './config'

const state = reactive({ path: normalize(window.location.pathname) })

function normalize(path) {
  const p = String(path || '/').replace(/\/+$/, '') || '/'
  return ROUTES.includes(p) ? p : '/'
}

export const route = state

export function navigate(path, { replace = false } = {}) {
  const next = normalize(path)
  if (next === state.path && !replace) return
  if (replace) window.history.replaceState({ path: next }, '', next)
  else window.history.pushState({ path: next }, '', next)
  state.path = next
}

function onPopState() {
  state.path = normalize(window.location.pathname)
}

let installed = false
export function initRouter() {
  if (installed) return
  installed = true
  window.addEventListener('popstate', onPopState)
}
