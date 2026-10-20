/** Опорный объект режима обучения — ЖК «Строгино 360». */
export const TRAINING_DEMO_SLUG = 'strogino'

export type DemoProjectLike = {
  id: string
  slug?: string | null
  name?: string | null
  developer?: string | { name?: string | null } | null
}

export function demoDeveloperName(p: DemoProjectLike): string {
  const d = p.developer
  if (!d) return ''
  return typeof d === 'string' ? d : (d.name || '')
}

export function isStroginoProject(p: DemoProjectLike): boolean {
  if (p.slug === TRAINING_DEMO_SLUG || p.id === TRAINING_DEMO_SLUG) return true
  return /строгин/i.test(p.name || '')
}

/** id проекта Строгино из портфеля (числовой API или slug в localStorage-режиме). */
export function resolveDemoProjectId(projects: DemoProjectLike[]): string {
  const hit = projects.find(isStroginoProject)
  if (hit) return String(hit.id)
  return TRAINING_DEMO_SLUG
}
