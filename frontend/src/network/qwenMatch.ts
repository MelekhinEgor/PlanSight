/**
 * Канонический матчинг через backend /api/ai/* — браузер не ходит в Ollama.
 */
import {
  catalogById,
  matchCanonicalWork,
  shortlistCanonical,
  type ScoredCandidate,
} from './canonicalMatch'
import type {CanonicalMatch} from './types'
import {WORK_TYPES_LTC} from '../admin/workTypesLtc'

export type QwenStatus = {
  available: boolean
  model: string
  detail?: string
}

let cachedStatus: QwenStatus | null = null

function catalogPayload() {
  return WORK_TYPES_LTC.map((w) => ({
    id: w.id,
    code: w.code,
    name: w.name,
    aliases: [],
  }))
}

export async function checkQwenAvailable(force = false): Promise<QwenStatus> {
  if (cachedStatus && !force) return cachedStatus
  try {
    const res = await fetch('/api/ai/status', {signal: AbortSignal.timeout(4000)})
    if (!res.ok) {
      cachedStatus = {available: false, model: 'backend', detail: `AI status HTTP ${res.status}`}
      return cachedStatus
    }
    const data = (await res.json()) as {
      ollama_configured?: boolean
      ollama_reachable?: boolean
      models?: {text_llm?: {id?: string; present?: boolean | null}}
      probe_error?: string
    }
    const model = data.models?.text_llm?.id || 'qwen2.5:7b'
    const ok = Boolean(data.ollama_configured && data.ollama_reachable)
    cachedStatus = {
      available: ok,
      model,
      detail: ok
        ? undefined
        : data.probe_error
          ? 'Помощник на сервере сейчас недоступен — используем сопоставление по названиям'
          : data.ollama_configured
            ? 'Помощник настроен, но не отвечает — сопоставление по названиям'
            : 'Помощник не настроен — сопоставление по названиям',
    }
    return cachedStatus
  } catch (e) {
    cachedStatus = {
      available: false,
      model: 'backend',
      detail: e instanceof Error ? 'Сервис ИИ недоступен — сопоставление по названиям' : 'Сервис ИИ недоступен',
    }
    return cachedStatus
  }
}

type LlmPick = {id: string | null; confidence: number; reason?: string}

function applyBackendMatch(
  base: CanonicalMatch,
  row: {
    canonical_work_id?: string | null
    canonical_work_code?: string | null
    canonical_work_name?: string | null
    mapping_status?: string
    needs_confirmation?: boolean
    candidates?: ScoredCandidate[]
    score?: number
  },
): CanonicalMatch {
  return {
    ...base,
    canonical_work_id: row.canonical_work_id ?? null,
    canonical_work_code: row.canonical_work_code ?? null,
    canonical_work_name: row.canonical_work_name ?? null,
    mapping_status: (row.mapping_status as CanonicalMatch['mapping_status']) || base.mapping_status,
    needs_confirmation: row.needs_confirmation ?? base.needs_confirmation,
    candidates: (row.candidates as ScoredCandidate[])?.slice(0, 5) || base.candidates,
  }
}

/**
 * Мэтчинг через backend. Fallback на локальный строковый match, если API недоступен.
 */
export async function matchAllCanonicalWithQwen(
  activities: {id: string; name: string}[],
): Promise<{matches: CanonicalMatch[]; used_qwen: boolean; qwen_detail?: string}> {
  const localBase = activities.map((a) => matchCanonicalWork(a.id, a.name))
  try {
    const res = await fetch('/api/ai/canonical-match', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        activities,
        catalog: catalogPayload(),
        use_llm: true,
      }),
      signal: AbortSignal.timeout(120000),
    })
    if (!res.ok) {
      const status = await checkQwenAvailable()
      return {matches: localBase, used_qwen: false, qwen_detail: status.detail || `canonical-match HTTP ${res.status}`}
    }
    const data = (await res.json()) as {
      matches?: Array<{
        activity_id?: string
        source_name?: string
        canonical_work_id?: string | null
        canonical_work_code?: string | null
        canonical_work_name?: string | null
        mapping_status?: string
        needs_confirmation?: boolean
        candidates?: ScoredCandidate[]
        score?: number
      }>
      used_llm?: boolean
      detail?: string
    }
    const byId = new Map((data.matches || []).map((m) => [String(m.activity_id), m]))
    const matches = localBase.map((m) => {
      const row = byId.get(m.activity_id)
      return row ? applyBackendMatch(m, row) : m
    })
    return {
      matches,
      used_qwen: Boolean(data.used_llm),
      qwen_detail: data.detail || (data.used_llm ? 'Сопоставление уточнено автоматически' : 'Сопоставление по названиям'),
    }
  } catch (e) {
    return {
      matches: localBase,
      used_qwen: false,
      qwen_detail: e instanceof Error ? 'Сервис сопоставления временно недоступен' : 'Сервис сопоставления недоступен',
    }
  }
}

/** @deprecated оставлен для type imports — shortlist по-прежнему локальный */
export function localShortlist(name: string, limit = 12) {
  return shortlistCanonical(name, limit)
}

export function localCatalogById() {
  return catalogById()
}
