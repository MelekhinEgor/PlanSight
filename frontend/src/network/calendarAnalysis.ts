import type {TemporalKind, TemporalRelation, ProposedDependency} from './types'

const DAY = 86400000

function toMs(iso: string) {
  return new Date(`${iso}T00:00:00Z`).getTime()
}

function diffDays(a: string, b: string) {
  return Math.round((toMs(b) - toMs(a)) / DAY)
}

function pad(n: number) {
  return String(n).padStart(2, '0')
}

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`
}

function isWeekend(iso: string) {
  const day = new Date(`${iso}T00:00:00Z`).getUTCDay()
  return day === 0 || day === 6
}

/** Следующий рабочий день после даты (сб/вс пропускаются). */
export function nextWorkingDay(iso: string): string {
  let d = addDays(iso, 1)
  while (isWeekend(d)) d = addDays(d, 1)
  return d
}

/**
 * Базовое правило PlanSight: последовательные даты → FS.
 * True, если successor начинается на следующий календарный день
 * или на ближайший следующий рабочий день после окончания predecessor.
 */
export function isImmediateSequence(predEnd: string, succStart: string): boolean {
  if (succStart <= predEnd) return false
  if (diffDays(predEnd, succStart) === 1) return true
  return succStart === nextWorkingDay(predEnd)
}

export type DatedActivity = {
  id: string
  planned_start: string | null
  planned_end: string | null
  wbs_node_id?: string | null
  code?: string | null
}

/** Календарный анализ пары работ. Не создаёт технологических зависимостей. */
export function analyzePair(a: DatedActivity, b: DatedActivity): TemporalRelation | null {
  if (!a.planned_start || !a.planned_end || !b.planned_start || !b.planned_end) return null
  // Порядок: кто раньше начинается — predecessor в записи отношения
  const [pred, succ] = a.planned_start <= b.planned_start ? [a, b] : [b, a]
  const ps = pred.planned_start!
  const pe = pred.planned_end!
  const ss = succ.planned_start!
  const se = succ.planned_end!

  const startDelta = diffDays(ps, ss)
  const finishDelta = diffDays(pe, se)
  const overlapStart = Math.max(toMs(ps), toMs(ss))
  const overlapEnd = Math.min(toMs(pe), toMs(se))
  const overlapDays = overlapEnd >= overlapStart ? Math.round((overlapEnd - overlapStart) / DAY) + 1 : 0
  const gapDays = toMs(ss) > toMs(pe) ? diffDays(pe, ss) - 1 : 0

  let kind: TemporalKind
  if (ps === ss && pe === se) kind = 'parallel'
  else if (ps === ss) kind = 'same_start'
  else if (pe === se) kind = 'same_finish'
  else if (overlapDays > 0 && (ss < pe && se > ps)) {
    kind = ss > ps && se < pe || ps > ss && pe < se ? 'partial_overlap' : 'parallel'
    if (ss < pe && se > pe && ss > ps) kind = 'partial_overlap'
    else if (overlapDays > 0) kind = pe < se && ss <= pe ? (ss === ps ? 'same_start' : 'partial_overlap') : 'parallel'
  } else if (toMs(ss) === toMs(pe) + DAY || toMs(ss) > toMs(pe)) {
    kind = gapDays > 0 ? 'gap' : 'sequential'
  } else {
    kind = 'parallel'
  }

  // Уточнение: полное включение / пересечение
  if (overlapDays > 0 && toMs(ss) < toMs(pe) && toMs(ss) > toMs(ps)) kind = 'partial_overlap'
  if (overlapDays > 0 && ps === ss) kind = 'same_start'
  if (overlapDays > 0 && pe === se) kind = 'same_finish'
  if (overlapDays <= 0 && isImmediateSequence(pe, ss)) kind = 'sequential'
  else if (overlapDays <= 0 && toMs(ss) > toMs(pe) + DAY) kind = 'gap'

  return {
    predecessor_activity_id: pred.id,
    successor_activity_id: succ.id,
    kind,
    gap_days: Math.max(0, gapDays),
    overlap_days: Math.max(0, overlapDays),
    start_delta_days: startDelta,
    finish_delta_days: finishDelta,
  }
}

/**
 * Строит временные отношения для пар с датами.
 * По умолчанию — пары в одном WBS или с пересечением/последовательностью (не «все со всеми вслепую»).
 */
export function buildTemporalRelations(activities: DatedActivity[]): TemporalRelation[] {
  const dated = activities.filter(a => a.planned_start && a.planned_end)
  const out: TemporalRelation[] = []
  for (let i = 0; i < dated.length; i++) {
    for (let j = i + 1; j < dated.length; j++) {
      const a = dated[i], b = dated[j]
      const sameWbs = !!(a.wbs_node_id && a.wbs_node_id === b.wbs_node_id)
      const rel = analyzePair(a, b)
      if (!rel) continue
      const relevant =
        sameWbs ||
        rel.kind === 'sequential' ||
        rel.kind === 'gap' ||
        rel.kind === 'partial_overlap' ||
        rel.kind === 'parallel' ||
        rel.kind === 'same_start' ||
        rel.kind === 'same_finish'
      if (relevant) out.push(rel)
    }
  }
  return out
}

/** Lag для FS: дни между окончанием pred и началом succ (0 если на следующий календарный день). */
export function lagFromFs(predEnd: string, succStart: string): number {
  const gap = diffDays(predEnd, succStart) - 1
  return Math.max(0, gap)
}

/** Lag для SS: разница начал. */
export function lagFromSs(predStart: string, succStart: string): number {
  return Math.max(0, diffDays(predStart, succStart))
}

/** Lag для FF: разница окончаний. */
export function lagFromFf(predEnd: string, succEnd: string): number {
  return Math.max(0, diffDays(predEnd, succEnd))
}

function scopeKey(a: DatedActivity): string {
  if (a.wbs_node_id) return `wbs:${a.wbs_node_id}`
  const code = (a.code ?? '').trim()
  if (code) {
    const parts = code.split('.').filter(Boolean)
    if (parts.length >= 2) return `code:${parts.slice(0, 2).join('.')}`
    if (parts.length === 1) return `code:${parts[0]}`
  }
  return `id:${a.id}`
}

function uid() {
  return Math.random().toString(36).slice(2, 10)
}

/**
 * Базовое правило: последовательные даты → подтверждённая связь FS.
 * Внутри одного WBS/скоупа: у каждой работы не более одного такого предшественника
 * (ближайшее окончание перед стартом на следующий раб. день).
 * Не ждёт нейросеть / технологические шаблоны.
 */
export function restoreSequentialFs(
  activities: DatedActivity[],
  options?: {existingPairs?: Set<string>},
): ProposedDependency[] {
  const existing = options?.existingPairs ?? new Set<string>()
  const dated = activities.filter(a => a.planned_start && a.planned_end) as (DatedActivity & {
    planned_start: string
    planned_end: string
  })[]

  const byScope = new Map<string, typeof dated>()
  for (const a of dated) {
    const key = scopeKey(a)
    byScope.set(key, [...(byScope.get(key) ?? []), a])
  }

  const out: ProposedDependency[] = []
  const seen = new Set<string>()

  for (const [, scoped] of byScope) {
    for (const succ of scoped) {
      let best: {pred: (typeof dated)[0]; gap: number} | null = null
      for (const pred of scoped) {
        if (pred.id === succ.id) continue
        if (!isImmediateSequence(pred.planned_end, succ.planned_start)) continue
        const key = `${pred.id}>${succ.id}`
        const rev = `${succ.id}>${pred.id}`
        if (existing.has(key) || seen.has(key) || seen.has(rev) || existing.has(rev)) continue
        const gap = diffDays(pred.planned_end, succ.planned_start)
        if (!best || gap < best.gap || (gap === best.gap && pred.planned_end > best.pred.planned_end)) {
          best = {pred, gap}
        }
      }
      if (!best) continue
      const key = `${best.pred.id}>${succ.id}`
      seen.add(key)
      const lag = lagFromFs(best.pred.planned_end, succ.planned_start)
      out.push({
        id: `cal-fs-${uid()}`,
        predecessor_activity_id: best.pred.id,
        successor_activity_id: succ.id,
        relation_type: 'FS',
        lag_days: lag,
        rule_id: 'sequential-fs',
        confidence: 'high',
        status: 'confirmed',
        requires_confirmation: false,
        reason: 'Последовательные даты → FS (следующий рабочий день)',
        source: 'calendar',
        scope_key: scopeKey(succ),
        chain: null,
      })
    }
  }

  return out
}
