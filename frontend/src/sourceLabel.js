// 三段式降级口径（V2_PLAN.md 第 8.4 节）唯一判定处：
//   source=primary 且 corrected=false →【主模型生成】
//   source=primary 且 corrected=true  →【主模型生成·已校正】
//   source=fallback 或 degraded=true  →【离线降级策略】
// 判定只依赖接口返回的 source / corrected / degraded，前端不猜、不分叉。
export function sourceTag(res) {
  const source = res?.source || ''
  const degraded = !!res?.degraded || source === 'fallback'
  if (degraded) return { text: '离线降级策略', kind: 'red', key: 'fallback' }
  if (res?.corrected) return { text: '主模型生成·已校正', kind: 'warn', key: 'corrected' }
  return { text: '主模型生成', kind: 'green', key: 'primary' }
}

// 对话接口没有 source 字段，只有 degraded：degraded=true 即离线降级
export function chatTag(res) {
  return sourceTag({ source: res?.degraded ? 'fallback' : 'primary', corrected: false, degraded: res?.degraded })
}
