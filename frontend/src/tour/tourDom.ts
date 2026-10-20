/** Поиск цели тура: при нескольких узлах берём самый крупный видимый. */

export function queryTourTarget(target: string): Element | null {
  const safe = typeof CSS !== 'undefined' && typeof CSS.escape === 'function' ? CSS.escape(target) : target.replace(/"/g, '')
  const nodes = Array.from(document.querySelectorAll(`[data-tour-id="${safe}"]`))
  if (!nodes.length) return null
  if (nodes.length === 1) return nodes[0]

  let best: Element | null = null
  let bestArea = 0
  for (const el of nodes) {
    const r = el.getBoundingClientRect()
    if (r.width < 4 || r.height < 4) continue
    const style = window.getComputedStyle(el)
    if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity) === 0) continue
    const area = r.width * r.height
    if (area > bestArea) {
      bestArea = area
      best = el
    }
  }
  return best || nodes[nodes.length - 1]
}
