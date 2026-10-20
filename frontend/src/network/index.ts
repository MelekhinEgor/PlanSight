import {buildTemporalRelations, restoreSequentialFs} from './calendarAnalysis'
import {matchAllCanonical} from './canonicalMatch'
import {matchAllCanonicalWithQwen} from './qwenMatch'
import {CHAIN_LABELS, getDependencyRules} from './restoreDependencies'
import type {CanonicalMatch, NetworkRecoveryModel, ProposalGroup, ProposedDependency} from './types'

export type RecoverInputActivity = {
  id: string
  name: string
  planned_start: string | null
  planned_end: string | null
  wbs_node_id?: string | null
  code?: string | null
}

export type ExistingDep = {
  predecessor_activity_id: string
  successor_activity_id: string
  relation_type: string | null
  lag_days: number
}

function groupStatus(items: ProposedDependency[]): ProposalGroup['status'] {
  const open = items.filter(p => p.status === 'proposed')
  const conf = items.filter(p => p.status === 'confirmed')
  const rej = items.filter(p => p.status === 'rejected')
  if (open.length && !conf.length && !rej.length) return 'proposed'
  if (conf.length && !open.length && !rej.length) return 'confirmed'
  if (rej.length && !open.length && !conf.length) return 'rejected'
  if (conf.length && !open.length) return 'confirmed'
  if (rej.length && !open.length) return 'rejected'
  return 'mixed'
}

export function buildProposalGroups(proposed: ProposedDependency[]): ProposalGroup[] {
  const rules = getDependencyRules()
  const ruleMap = new Map(rules.map(r => [r.id, r]))
  const byKey = new Map<string, ProposedDependency[]>()

  for (const p of proposed) {
    if (p.source === 'excel' || p.source === 'calendar') continue
    const key = p.rule_id ?? `misc-${p.relation_type}`
    byKey.set(key, [...(byKey.get(key) ?? []), p])
  }

  const groups: ProposalGroup[] = []
  for (const [id, items] of byKey) {
    const rule = ruleMap.get(id)
    const lags = items.map(i => i.lag_days)
    const scopes = new Set(items.map(i => i.scope_key).filter(Boolean))
    const confidence = rule?.confidence ?? items[0]?.confidence ?? 'medium'
    const chain = rule?.chain ?? items[0]?.chain ?? null
    groups.push({
      id,
      title: rule?.note ?? items[0]?.reason ?? id,
      relation_type: rule?.relation ?? items[0]?.relation_type ?? 'FS',
      confidence,
      proposal_ids: items.map(i => i.id),
      scope_count: scopes.size || 1,
      lag_min: Math.min(...lags),
      lag_max: Math.max(...lags),
      chain,
      chain_label: chain ? CHAIN_LABELS[chain] ?? chain : null,
      recommended: confidence === 'high' && !(rule?.requires_confirmation),
      status: groupStatus(items),
    })
  }

  return groups.sort((a, b) => {
    const chainCmp = (a.chain_label ?? 'яяя').localeCompare(b.chain_label ?? 'яяя', 'ru')
    if (chainCmp) return chainCmp
    return a.title.localeCompare(b.title, 'ru')
  })
}

/**
 * Полный пайплайн: календарный анализ → CanonicalWork → авто-FS по датам.
 * Базовое правило: последовательные даты → FS (без нейросети).
 * Исходные даты не меняет. Excel-связи сохраняются и не заменяются.
 */
export function recoverNetworkModel(
  activities: RecoverInputActivity[],
  excelDeps: ExistingDep[],
  canonical_matches?: CanonicalMatch[],
): NetworkRecoveryModel {
  const original_calendar = activities.map(a => ({
    activity_id: a.id,
    planned_start: a.planned_start,
    planned_end: a.planned_end,
  }))

  const temporal_relations = buildTemporalRelations(activities)
  const matches = canonical_matches ?? matchAllCanonical(activities)

  const fromExcel: ProposedDependency[] = excelDeps
    .filter(d => d.predecessor_activity_id)
    .map((d, i) => ({
      id: `excel-${i}-${d.predecessor_activity_id}`,
      predecessor_activity_id: d.predecessor_activity_id,
      successor_activity_id: d.successor_activity_id,
      relation_type: (d.relation_type as ProposedDependency['relation_type']) || 'FS',
      lag_days: d.lag_days ?? 0,
      rule_id: null,
      confidence: 'high' as const,
      status: 'confirmed' as const,
      requires_confirmation: false,
      reason: 'Связь из Excel',
      source: 'excel' as const,
      scope_key: null,
      chain: null,
    }))

  const existingPairs = new Set(fromExcel.map(p => `${p.predecessor_activity_id}>${p.successor_activity_id}`))
  // Базовое правило PlanSight: последовательные даты → FS (подтверждено сразу)
  const fromCalendar = restoreSequentialFs(activities, {existingPairs})
  // Шаблоны технологических связей отключены
  const fromRules: ProposedDependency[] = []
  const proposed = [...fromExcel, ...fromCalendar, ...fromRules]
  const groups: ProposalGroup[] = []

  const linked = new Set<string>()
  proposed.forEach(p => {
    if (p.status !== 'rejected') {
      linked.add(p.predecessor_activity_id)
      linked.add(p.successor_activity_id)
    }
  })

  const dated = activities.filter(a => a.planned_start && a.planned_end)
  const unlinked_count = dated.filter(a => !linked.has(a.id)).length
  const need_confirmation =
    proposed.filter(p => p.status === 'proposed' && p.requires_confirmation).length +
    matches.filter(m => m.needs_confirmation && m.mapping_status === 'AMBIGUOUS').length

  return {
    analyzed_at: new Date().toISOString(),
    original_calendar,
    temporal_relations,
    canonical_matches: matches,
    proposed,
    groups,
    summary: {
      activities_loaded: activities.length,
      proposed_count: fromRules.length,
      need_confirmation,
      unlinked_count,
      excel_deps_kept: fromExcel.length,
      ambiguous_mappings: matches.filter(m => m.mapping_status === 'AMBIGUOUS').length,
      temporal_pairs: temporal_relations.length,
      group_count: groups.length,
      auto_ready: fromCalendar.length,
    },
    forecast_mode: fromExcel.length || fromCalendar.length ? 'confirmed' : 'preliminary',
  }
}

/** Импорт / превью: мэтчинг через Qwen 3.5 9B (Ollama), с fallback на строки. */
export async function recoverNetworkModelWithQwen(
  activities: RecoverInputActivity[],
  excelDeps: ExistingDep[],
): Promise<NetworkRecoveryModel & {qwen?: {used: boolean; detail?: string}}> {
  const {matches, used_qwen, qwen_detail} = await matchAllCanonicalWithQwen(activities)
  const model = recoverNetworkModel(activities, excelDeps, matches)
  return {...model, qwen: {used: used_qwen, detail: qwen_detail}}
}

export function applyCanonicalToActivities<T extends {id: string; name: string; canonical_work_id: string | null; canonical_work_code: string | null; canonical_work_name: string | null; mapping_status: string}>(
  activities: T[],
  model: NetworkRecoveryModel,
): T[] {
  const map = new Map(model.canonical_matches.map(m => [m.activity_id, m]))
  return activities.map(a => {
    const m = map.get(a.id)
    if (!m) return a
    return {
      ...a,
      canonical_work_id: m.canonical_work_id,
      canonical_work_code: m.canonical_work_code,
      canonical_work_name: m.canonical_work_name,
      mapping_status: m.mapping_status,
    }
  })
}

/** Подтверждённые авто-FS из календарного правила → реальные зависимости графика. */
export function calendarDepsFromRecovery(
  model: NetworkRecoveryModel,
): {predecessor_activity_id: string; successor_activity_id: string; relation_type: string; lag_days: number}[] {
  return model.proposed
    .filter(p => p.source === 'calendar' && p.status === 'confirmed')
    .map(p => ({
      predecessor_activity_id: p.predecessor_activity_id,
      successor_activity_id: p.successor_activity_id,
      relation_type: p.relation_type,
      lag_days: p.lag_days,
    }))
}

export function refreshGroups(model: NetworkRecoveryModel): NetworkRecoveryModel {
  const groups = buildProposalGroups(model.proposed)
  const open = model.proposed.filter(p => p.status === 'proposed' && p.source === 'rule')
  const calendar = model.proposed.filter(p => p.source === 'calendar' && p.status === 'confirmed')
  return {
    ...model,
    groups,
    summary: {
      ...model.summary,
      proposed_count: open.length,
      need_confirmation: open.filter(p => p.requires_confirmation).length,
      group_count: groups.length,
      auto_ready: calendar.length,
    },
    forecast_mode: open.length ? 'preliminary' : 'confirmed',
  }
}

export * from './types'
export * from './calendarAnalysis'
export * from './canonicalMatch'
export * from './qwenMatch'
export * from './restoreDependencies'
