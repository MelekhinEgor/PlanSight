/**
 * What-if пересмотр прогноза КСГ после подтверждения предупреждения.
 * Не публикует официальный график — только локальный прогнозный контур.
 */

export type RevisionActivity = {
  id: string
  name?: string | null
  planned_start?: string | null
  planned_end?: string | null
  forecast_end?: string | null
}

export type RevisionDependency = {
  predecessor_activity_id: string
  successor_activity_id: string
  relation_type?: string | null
  lag_days?: number | null
}

export type ScheduleRevisionPatch = {
  activityId: string
  name?: string | null
  prevForecast: string | null
  nextForecast: string
  shiftedDays: number
  reason: 'driver' | 'successor_push' | 'float_absorb'
}

export type ScheduleRevisionResult = {
  status: 'revised' | 'absorbed' | 'unavailable'
  notOfficial: true
  driverActivityId: string
  impactDays: number
  projectFinishBefore: string | null
  projectFinishAfter: string | null
  projectFinishDeltaDays: number
  absorbedByFloatDays: number
  affectedSuccessors: number
  patches: ScheduleRevisionPatch[]
  messageRu: string
  summaryLines: string[]
}

function parseIso(iso: string | null | undefined): Date | null {
  if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null
  const d = new Date(`${iso}T00:00:00Z`)
  return Number.isNaN(d.getTime()) ? null : d
}

function fmtIso(d: Date): string {
  const y = d.getUTCFullYear()
  const m = String(d.getUTCMonth() + 1).padStart(2, '0')
  const day = String(d.getUTCDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function addCalendarDays(iso: string, days: number): string {
  const d = parseIso(iso)
  if (!d) return iso
  d.setUTCDate(d.getUTCDate() + days)
  return fmtIso(d)
}

function daysBetween(a: string | null | undefined, b: string | null | undefined): number | null {
  const da = parseIso(a || null)
  const db = parseIso(b || null)
  if (!da || !db) return null
  return Math.round((db.getTime() - da.getTime()) / 86400000)
}

function maxIso(dates: (string | null | undefined)[]): string | null {
  let best: string | null = null
  for (const d of dates) {
    if (!d || !parseIso(d)) continue
    if (!best || d > best) best = d
  }
  return best
}

function activeEnd(a: RevisionActivity): string | null {
  const pe = a.planned_end
  const fe = a.forecast_end
  if (pe && fe && fe > pe) return fe
  return pe || fe || null
}

/**
 * Пересчёт прогноза: сдвиг driver + каскад по FS с поглощением свободного резерва.
 */
export function reviseScheduleOnConfirm(input: {
  activityId: string
  /** Дни влияния из расчёта прогресса (может быть 0). */
  impactDays: number
  /** Явная прогнозная дата окончания driver (приоритетнее impactDays). */
  forecastFinish?: string | null
  activities: RevisionActivity[]
  dependencies?: RevisionDependency[]
}): ScheduleRevisionResult {
  const acts = input.activities.map((a) => ({ ...a }))
  const byId = new Map(acts.map((a) => [a.id, a]))
  const driver = byId.get(input.activityId)
  const deps = (input.dependencies || []).filter((d) => (d.relation_type || 'FS') === 'FS')

  if (!driver) {
    return {
      status: 'unavailable',
      notOfficial: true,
      driverActivityId: input.activityId,
      impactDays: input.impactDays,
      projectFinishBefore: null,
      projectFinishAfter: null,
      projectFinishDeltaDays: 0,
      absorbedByFloatDays: 0,
      affectedSuccessors: 0,
      patches: [],
      messageRu: 'Пересмотр недоступен: работа КСГ не найдена.',
      summaryLines: ['Нет привязки к строке графика'],
    }
  }

  const beforeFinish = maxIso(acts.map(activeEnd))
  const baseEnd = driver.planned_end || driver.forecast_end
  if (!baseEnd) {
    return {
      status: 'unavailable',
      notOfficial: true,
      driverActivityId: driver.id,
      impactDays: input.impactDays,
      projectFinishBefore: beforeFinish,
      projectFinishAfter: beforeFinish,
      projectFinishDeltaDays: 0,
      absorbedByFloatDays: 0,
      affectedSuccessors: 0,
      patches: [],
      messageRu: 'Пересмотр недоступен: у работы нет плановой даты окончания.',
      summaryLines: ['Нет планового окончания у работы'],
    }
  }

  const impact = Math.max(0, Math.round(input.impactDays || 0))
  let driverNext: string =
    input.forecastFinish && parseIso(input.forecastFinish)
      ? input.forecastFinish
      : addCalendarDays(baseEnd, impact)

  // Не уводим прогноз раньше текущего планового конца
  if (driver.planned_end && driverNext < driver.planned_end) driverNext = driver.planned_end

  const driverShift = daysBetween(driver.forecast_end || driver.planned_end, driverNext) || 0
  const patches: ScheduleRevisionPatch[] = []
  const prevDriver = driver.forecast_end
  driver.forecast_end = driverNext
  patches.push({
    activityId: driver.id,
    name: driver.name,
    prevForecast: prevDriver ?? null,
    nextForecast: driverNext,
    shiftedDays: Math.max(0, driverShift),
    reason: 'driver',
  })

  let remainingPush = Math.max(0, daysBetween(baseEnd, driverNext) || impact)
  let absorbed = 0
  let affectedSuccessors = 0

  // BFS по FS-последователям
  const queue = [driver.id]
  const seen = new Set<string>([driver.id])
  while (queue.length && remainingPush > 0) {
    const predId = queue.shift()!
    const pred = byId.get(predId)
    if (!pred?.forecast_end && !pred?.planned_end) continue
    const predEnd = pred.forecast_end || pred.planned_end!

    for (const link of deps.filter((d) => d.predecessor_activity_id === predId)) {
      const succ = byId.get(link.successor_activity_id)
      if (!succ || seen.has(succ.id)) continue
      seen.add(succ.id)
      queue.push(succ.id)

      const lag = Number(link.lag_days) || 0
      const requiredStart = addCalendarDays(predEnd, 1 + lag)
      const succStart = succ.planned_start
      const succEnd = succ.planned_end || succ.forecast_end
      if (!succStart || !succEnd) continue

      const floatDays = Math.max(0, daysBetween(requiredStart, succStart) || 0)
      if (floatDays >= remainingPush) {
        absorbed += remainingPush
        patches.push({
          activityId: succ.id,
          name: succ.name,
          prevForecast: succ.forecast_end ?? null,
          nextForecast: succ.forecast_end || succEnd,
          shiftedDays: 0,
          reason: 'float_absorb',
        })
        remainingPush = 0
        break
      }

      const push = remainingPush - floatDays
      absorbed += floatDays
      if (push <= 0) continue

      const prev = succ.forecast_end
      const next = addCalendarDays(succ.forecast_end || succEnd, push)
      succ.forecast_end = next
      affectedSuccessors += 1
      patches.push({
        activityId: succ.id,
        name: succ.name,
        prevForecast: prev ?? null,
        nextForecast: next,
        shiftedDays: push,
        reason: 'successor_push',
      })
      remainingPush = push
    }
  }

  const afterFinish = maxIso(acts.map(activeEnd))
  const projectDelta = Math.max(0, daysBetween(beforeFinish, afterFinish) || 0)
  const driverDelta = Math.max(0, daysBetween(baseEnd, driverNext) || impact)

  const summaryLines: string[] = []
  if (driverDelta > 0) {
    summaryLines.push(`Дата завершения работы смещается на +${driverDelta} дн.`)
  } else {
    summaryLines.push('Срок завершения этой работы по прогнозу не меняется')
  }
  if (absorbed > 0) {
    summaryLines.push(`Часть сдвига (${absorbed} дн.) поглощена резервом на критическом пути`)
  }
  if (projectDelta > 0) {
    summaryLines.push(`Прогнозный финиш проекта смещается на +${projectDelta} дн.`)
  } else {
    summaryLines.push('Основное строительство в датах не изменяется — запас сети удерживает финиш проекта')
  }

  const status: ScheduleRevisionResult['status'] =
    driverDelta <= 0 && projectDelta <= 0
      ? 'absorbed'
      : patches.some((p) => p.reason === 'driver' || p.reason === 'successor_push')
        ? 'revised'
        : 'unavailable'

  const messageRu =
    status === 'absorbed'
      ? `Сигнал учтён: сдвиг работы поглощён резервом на критическом пути. Финиш проекта без изменений.`
      : `График пересмотрен с учётом критического пути: срок работы +${driverDelta} дн.` +
        (projectDelta > 0 ? `, финиш проекта +${projectDelta} дн.` : ', сроки основного строительства без изменений.')

  return {
    status,
    notOfficial: true,
    driverActivityId: driver.id,
    impactDays: driverDelta,
    projectFinishBefore: beforeFinish,
    projectFinishAfter: afterFinish,
    projectFinishDeltaDays: projectDelta,
    absorbedByFloatDays: absorbed,
    affectedSuccessors,
    patches: patches.filter((p) => p.reason !== 'float_absorb' || p.shiftedDays === 0),
    messageRu,
    summaryLines,
  }
}

/** Применить патчи к списку активностей (immutable). */
export function applyRevisionPatches<T extends RevisionActivity>(
  activities: T[],
  patches: ScheduleRevisionPatch[],
): T[] {
  const map = new Map(patches.filter((p) => p.shiftedDays > 0 || p.reason === 'driver').map((p) => [p.activityId, p]))
  return activities.map((a) => {
    const p = map.get(a.id)
    if (!p) return a
    return { ...a, forecast_end: p.nextForecast }
  })
}

/** Сессионный what-if: живёт до закрытия вкладки/браузера, не пишется в КСГ. */
export const SCHEDULE_REVISION_SESSION_KEY = 'plansight.schedule.revision.session.v1'

export type SessionScheduleRevision = {
  projectId: string
  updatedAt: string
  driverActivityId: string
  messageRu: string
  summaryLines: string[]
  patches: ScheduleRevisionPatch[]
  revisedActivityIds: string[]
  status: ScheduleRevisionResult['status']
  impactDays: number
  projectFinishDeltaDays: number
  absorbedByFloatDays: number
  affectedSuccessors: number
}

function sessionKey(projectId: string) {
  return `${SCHEDULE_REVISION_SESSION_KEY}.${projectId}`
}

export function loadSessionScheduleRevision(projectId: string): SessionScheduleRevision | null {
  if (!projectId || typeof sessionStorage === 'undefined') return null
  try {
    const raw = sessionStorage.getItem(sessionKey(projectId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as SessionScheduleRevision
    if (!parsed || parsed.projectId !== projectId || !Array.isArray(parsed.patches)) return null
    return parsed
  } catch {
    return null
  }
}

export function saveSessionScheduleRevision(
  projectId: string,
  revision: ScheduleRevisionResult,
): SessionScheduleRevision | null {
  if (!projectId || typeof sessionStorage === 'undefined') return null
  if (revision.status === 'unavailable' || !revision.patches.length) return null
  const payload: SessionScheduleRevision = {
    projectId,
    updatedAt: new Date().toISOString(),
    driverActivityId: revision.driverActivityId,
    messageRu: revision.messageRu,
    summaryLines: revision.summaryLines,
    patches: revision.patches,
    revisedActivityIds: revision.patches
      .filter((p) => p.shiftedDays > 0 || p.reason === 'driver')
      .map((p) => p.activityId),
    status: revision.status,
    impactDays: revision.impactDays,
    projectFinishDeltaDays: revision.projectFinishDeltaDays,
    absorbedByFloatDays: revision.absorbedByFloatDays,
    affectedSuccessors: revision.affectedSuccessors,
  }
  try {
    sessionStorage.setItem(sessionKey(projectId), JSON.stringify(payload))
  } catch {
    /* quota / private mode */
  }
  return payload
}

export function clearSessionScheduleRevision(projectId?: string) {
  if (typeof sessionStorage === 'undefined') return
  try {
    if (projectId) {
      sessionStorage.removeItem(sessionKey(projectId))
      return
    }
    const prefix = `${SCHEDULE_REVISION_SESSION_KEY}.`
    for (let i = sessionStorage.length - 1; i >= 0; i -= 1) {
      const k = sessionStorage.key(i)
      if (k && k.startsWith(prefix)) sessionStorage.removeItem(k)
    }
  } catch {
    /* ignore */
  }
}

/** Наложить сохранённый сессионный what-if на загруженный график. */
export function applySessionScheduleRevision<T extends RevisionActivity>(
  projectId: string,
  activities: T[],
): { activities: T[]; overlay: SessionScheduleRevision | null } {
  const overlay = loadSessionScheduleRevision(projectId)
  if (!overlay?.patches?.length) return { activities, overlay: null }
  return { activities: applyRevisionPatches(activities, overlay.patches), overlay }
}
