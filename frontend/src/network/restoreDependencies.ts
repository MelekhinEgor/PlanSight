import rulesJson from './dependency_rules.json'
import {lagFromFf, lagFromFs, lagFromSs} from './calendarAnalysis'
import {nameMatchesAlias} from './canonicalMatch'
import type {DependencyRule, ProposedDependency, RelationType} from './types'

const rules = (rulesJson as {rules: DependencyRule[]}).rules
const MAX_GAP_DAYS = 120

export type ActivityForRestore = {
  id: string
  name: string
  planned_start: string | null
  planned_end: string | null
  canonical_work_name?: string | null
  wbs_node_id?: string | null
  code?: string | null
}

function uid() {
  return Math.random().toString(36).slice(2, 10)
}

const DAY = 86400000
function diffDays(a: string, b: string) {
  return Math.round((new Date(`${b}T00:00:00Z`).getTime() - new Date(`${a}T00:00:00Z`).getTime()) / DAY)
}

/** Скоуп: WBS, иначе префикс кода до 2 уровней (1.2.3 → 1.2). */
export function scopeKey(a: ActivityForRestore): string {
  if (a.wbs_node_id) return `wbs:${a.wbs_node_id}`
  const code = (a.code ?? '').trim()
  if (code) {
    const parts = code.split('.').filter(Boolean)
    if (parts.length >= 2) return `code:${parts.slice(0, 2).join('.')}`
    if (parts.length === 1) return `code:${parts[0]}`
  }
  return `id:${a.id}`
}

function matchesRuleSide(a: ActivityForRestore, aliases: string[]) {
  return nameMatchesAlias(a.name, aliases) || (!!a.canonical_work_name && nameMatchesAlias(a.canonical_work_name, aliases))
}

function calcLag(
  mode: DependencyRule['lag_mode'],
  relation: RelationType,
  pred: ActivityForRestore,
  succ: ActivityForRestore,
  fixed?: number,
): number {
  if (mode === 'fixed') return fixed ?? 0
  if (!pred.planned_start || !pred.planned_end || !succ.planned_start || !succ.planned_end) return 0
  if (mode === 'calendar_ss' || relation === 'SS') return lagFromSs(pred.planned_start, succ.planned_start)
  if (mode === 'calendar_ff' || relation === 'FF') return lagFromFf(pred.planned_end, succ.planned_end)
  return lagFromFs(pred.planned_end, succ.planned_start)
}

/** Метрика «близости» для выбора одного successor внутри скоупа (меньше = лучше). */
function proximityScore(rule: DependencyRule, pred: ActivityForRestore, succ: ActivityForRestore): number | null {
  if (!pred.planned_start || !pred.planned_end || !succ.planned_start || !succ.planned_end) return null
  if (rule.relation === 'FF') {
    if (succ.planned_end < pred.planned_end) return null
    const gap = diffDays(pred.planned_end, succ.planned_end)
    if (gap > MAX_GAP_DAYS) return null
    return gap
  }
  if (rule.relation === 'SS' || rule.relation === 'SF') {
    if (succ.planned_start < pred.planned_start) return null
    const gap = diffDays(pred.planned_start, succ.planned_start)
    if (gap > MAX_GAP_DAYS) return null
    return gap
  }
  if (succ.planned_start < pred.planned_start) return null
  const gap = Math.max(0, diffDays(pred.planned_end, succ.planned_start) - 1)
  if (gap > MAX_GAP_DAYS) return null
  if (succ.planned_start < pred.planned_end) return gap + 0.5
  return gap
}

function hasPath(
  edges: {predecessor_activity_id: string; successor_activity_id: string}[],
  from: string,
  to: string,
): boolean {
  const adj = new Map<string, string[]>()
  edges.forEach(d => {
    adj.set(d.predecessor_activity_id, [...(adj.get(d.predecessor_activity_id) ?? []), d.successor_activity_id])
  })
  const stack = [from]
  const seen = new Set<string>()
  while (stack.length) {
    const n = stack.pop()!
    if (n === to) return true
    if (seen.has(n)) continue
    seen.add(n)
    ;(adj.get(n) ?? []).forEach(x => stack.push(x))
  }
  return false
}

/**
 * Восстановление технологических связей ТОЛЬКО по библиотеке правил.
 * Внутри скоупа — не более одного лучшего successor на (правило, pred).
 */
export function restoreFromRules(
  activities: ActivityForRestore[],
  options?: {existingPairs?: Set<string>},
): ProposedDependency[] {
  const existing = options?.existingPairs ?? new Set<string>()
  const proposed: ProposedDependency[] = []
  const seen = new Set<string>()

  const byScope = new Map<string, ActivityForRestore[]>()
  for (const a of activities) {
    const key = scopeKey(a)
    byScope.set(key, [...(byScope.get(key) ?? []), a])
  }

  for (const rule of rules) {
    for (const [, scoped] of byScope) {
      const preds = scoped.filter(a => matchesRuleSide(a, rule.predecessor_aliases))
      const succs = scoped.filter(a => matchesRuleSide(a, rule.successor_aliases))
      if (!preds.length || !succs.length) continue

      for (const pred of preds) {
        let best: {succ: ActivityForRestore; score: number} | null = null
        for (const succ of succs) {
          if (pred.id === succ.id) continue
          const key = `${pred.id}>${succ.id}`
          const rev = `${succ.id}>${pred.id}`
          if (seen.has(key) || existing.has(key) || seen.has(rev)) continue
          const score = proximityScore(rule, pred, succ)
          if (score == null) continue
          if (!best || score < best.score) best = {succ, score}
        }
        if (!best) continue
        if (hasPath(proposed, pred.id, best.succ.id)) continue

        const key = `${pred.id}>${best.succ.id}`
        seen.add(key)
        const lag = calcLag(rule.lag_mode, rule.relation, pred, best.succ, rule.fixed_lag)
        proposed.push({
          id: `prop-${rule.id}-${uid()}`,
          predecessor_activity_id: pred.id,
          successor_activity_id: best.succ.id,
          relation_type: rule.relation,
          lag_days: lag,
          rule_id: rule.id,
          confidence: rule.confidence,
          status: 'proposed',
          requires_confirmation: rule.requires_confirmation || rule.confidence !== 'high',
          reason: rule.note || `Правило ${rule.id}`,
          source: 'rule',
          scope_key: scopeKey(pred),
          chain: rule.chain ?? null,
        })
      }
    }
  }

  return proposed
}

export function wouldCreateCycle(
  edges: {predecessor_activity_id: string; successor_activity_id: string}[],
  candidate: {predecessor_activity_id: string; successor_activity_id: string},
): boolean {
  const all = [
    ...edges.filter(
      d =>
        !(
          d.predecessor_activity_id === candidate.predecessor_activity_id &&
          d.successor_activity_id === candidate.successor_activity_id
        ),
    ),
    candidate,
  ]
  const adj = new Map<string, string[]>()
  all.forEach(d => {
    adj.set(d.predecessor_activity_id, [...(adj.get(d.predecessor_activity_id) ?? []), d.successor_activity_id])
  })
  const target = candidate.predecessor_activity_id
  const stack = [candidate.successor_activity_id]
  const seen = new Set<string>()
  while (stack.length) {
    const n = stack.pop()!
    if (n === target) return true
    if (seen.has(n)) continue
    seen.add(n)
    ;(adj.get(n) ?? []).forEach(x => stack.push(x))
  }
  return false
}

export function filterAcyclic(proposals: ProposedDependency[]): ProposedDependency[] {
  const kept: ProposedDependency[] = []
  for (const p of proposals) {
    if (wouldCreateCycle(kept, p)) continue
    kept.push(p)
  }
  return kept
}

export function getDependencyRules(): DependencyRule[] {
  return rules
}

export const CHAIN_LABELS: Record<string, string> = {
  zero_cycle: 'Нулевой цикл',
  frame_envelope: 'Каркас и контур',
}
