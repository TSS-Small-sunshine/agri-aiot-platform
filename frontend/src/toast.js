// 极简全局 Toast：一个 reactive 列表 + 自动过期。不引任何依赖。
import { reactive } from 'vue'

let seq = 0
export const toasts = reactive([])

export function pushToast(text, { kind = 'info', ttl = 4000 } = {}) {
  const id = ++seq
  toasts.push({ id, text, kind })
  if (ttl > 0) setTimeout(() => dismissToast(id), ttl)
  return id
}

export function dismissToast(id) {
  const i = toasts.findIndex((t) => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}
