import {WORK_TYPES_LTC} from '../admin/workTypesLtc'
import type {CanonicalMatch} from './types'

export const QWEN_MODEL = 'qwen2.5:7b'
/** @deprecated Браузер не должен звать Ollama — используйте /api/ai/* */
export const OLLAMA_BASE = '/api/ai'

const normalize = (s: string) =>
  s
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/«|»|"/g, '')
    .replace(/[^a-zа-я0-9%]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()

/** Доп. алиасы Excel → ЛТЦ (пример: «Устройство свайного основания» → «Устройство свай»). */
const EXTRA_ALIASES: Record<string, string[]> = {
  'wt-44': ['котлован', 'разработка котлована'],
  'wt-45': ['устройство свайного основания', 'свайное основание', 'сваи'],
  'wt-53': ['фундаментная плита'],
  'wt-178': ['монолитный каркас', 'каркас', 'монолитный каркас секция 1', 'монолитный каркас секция 2'],
  'wt-114': ['кладка наружных стен', 'кладка'],
  'wt-59': ['ростверк', 'устройство ростверка'],
}

type CatalogItem = {id: string; code: string; name: string; aliases: string[]}

function buildCatalog(): CatalogItem[] {
  return WORK_TYPES_LTC.map(w => ({
    id: w.id,
    code: w.code,
    name: w.name,
    aliases: [normalize(w.name), ...(EXTRA_ALIASES[w.id] ?? []).map(normalize)],
  }))
}

function scoreName(query: string, item: CatalogItem): number {
  const q = normalize(query)
  if (!q) return 0
  if (item.aliases.some(a => a === q)) return 1
  if (item.aliases.some(a => a.includes(q) || q.includes(a))) {
    const best = Math.max(
      ...item.aliases.map(a => {
        if (a === q) return 1
        if (a.includes(q) || q.includes(a)) return Math.min(a.length, q.length) / Math.max(a.length, q.length)
        return 0
      }),
    )
    return 0.55 + best * 0.4
  }
  const qTokens = q.split(' ').filter(t => t.length > 2)
  if (!qTokens.length) return 0
  const nameTokens = normalize(item.name).split(' ')
  const hit = qTokens.filter(t => nameTokens.some(n => n.includes(t) || t.includes(n))).length
  return (hit / qTokens.length) * 0.7
}

export type ScoredCandidate = {id: string; code: string; name: string; score: number}

/** Shortlist для LLM: топ кандидатов даже при слабом строковом score. */
export function shortlistCanonical(sourceName: string, limit = 12): ScoredCandidate[] {
  const catalog = buildCatalog()
  return catalog
    .map(item => ({id: item.id, code: item.code, name: item.name, score: scoreName(sourceName, item)}))
    .filter(x => x.score >= 0.25)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
}

export function matchCanonicalWork(activityId: string, sourceName: string): CanonicalMatch {
  const scored = shortlistCanonical(sourceName, 8).filter(x => x.score >= 0.55)
  const top = scored[0]
  const second = scored[1]
  const ambiguous = !!(top && second && top.score - second.score < 0.08 && second.score >= 0.6)

  if (!top) {
    return {
      activity_id: activityId,
      source_name: sourceName,
      canonical_work_id: null,
      canonical_work_code: null,
      canonical_work_name: null,
      mapping_status: 'UNMAPPED',
      candidates: shortlistCanonical(sourceName, 5),
      needs_confirmation: true,
    }
  }

  if (ambiguous) {
    return {
      activity_id: activityId,
      source_name: sourceName,
      canonical_work_id: top.id,
      canonical_work_code: top.code,
      canonical_work_name: top.name,
      mapping_status: 'AMBIGUOUS',
      candidates: scored.slice(0, 5),
      needs_confirmation: true,
    }
  }

  return {
    activity_id: activityId,
    source_name: sourceName,
    canonical_work_id: top.id,
    canonical_work_code: top.code,
    canonical_work_name: top.name,
    mapping_status: 'MATCHED',
    candidates: scored.slice(0, 3),
    needs_confirmation: top.score < 0.85,
  }
}

export function matchAllCanonical(activities: {id: string; name: string}[]): CanonicalMatch[] {
  return activities.map(a => matchCanonicalWork(a.id, a.name))
}

export function nameMatchesAlias(name: string, aliases: string[]): boolean {
  const q = normalize(name)
  return aliases.some(alias => {
    const a = normalize(alias)
    return q === a || q.includes(a) || a.includes(q)
  })
}

export function catalogById(): Map<string, {id: string; code: string; name: string}> {
  return new Map(WORK_TYPES_LTC.map(w => [w.id, {id: w.id, code: w.code, name: w.name}]))
}
