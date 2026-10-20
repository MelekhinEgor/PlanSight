/**
 * Расчёт прогнозного влияния на срок (ТЗ Reports v2 §5.3).
 * Кадры сами по себе не являются основанием для численного прогноза.
 */

export const SCHEDULE_IMPACT_METHOD_ID = 'progress_rate_calendar_v1'
export const SCHEDULE_IMPACT_METHOD_VERSION = '1.0'

export type ProgressSnapshot = {
  date: string
  progressPercent: number
  source?: string
}

export type ScheduleImpactInputs = {
  plannedFinish: string
  asOfDate: string
  /** Текущий подтверждённый прогресс, % */
  currentProgressPercent: number
  /** Скорость, п.п. в календарный день (если уже известна) */
  dailyProgressPercentagePoints?: number | null
  /** Два и более датированных измерения для расчёта скорости */
  progressSnapshots?: ProgressSnapshot[]
  dayType?: 'calendar_days' | 'working_days'
}

export type ScheduleImpactOk = {
  status: 'calculated'
  plannedFinish: string
  asOfDate: string
  forecastFinish: string
  impactDays: number
  dayType: 'calendar_days' | 'working_days'
  currentProgressPercent: number
  remainingProgressPercent: number
  dailyProgressPercentagePoints: number
  remainingDurationCalendarDays: number
  methodId: string
  methodVersion: string
  calculationTrace: Record<string, unknown>
  summaryRu: string
}

export type ScheduleImpactBlocked = {
  status: 'not_calculated'
  reasons: string[]
  summaryRu: string
  methodId: string
  methodVersion: string
}

export type ScheduleImpactResult = ScheduleImpactOk | ScheduleImpactBlocked

function parseIsoDate(iso: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null
  const d = new Date(`${iso}T00:00:00Z`)
  return Number.isNaN(d.getTime()) ? null : d
}

function addCalendarDays(iso: string, days: number): string {
  const d = parseIsoDate(iso)
  if (!d) return iso
  d.setUTCDate(d.getUTCDate() + days)
  const y = d.getUTCFullYear()
  const m = String(d.getUTCMonth() + 1).padStart(2, '0')
  const day = String(d.getUTCDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function calendarDaysBetween(a: string, b: string): number | null {
  const da = parseIsoDate(a)
  const db = parseIsoDate(b)
  if (!da || !db) return null
  return Math.round((db.getTime() - da.getTime()) / 86400000)
}

function fmtRu(iso: string): string {
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  return m ? `${m[3]}.${m[2]}.${m[1]}` : iso
}

function rateFromSnapshots(snapshots: ProgressSnapshot[]): { rate: number; interval: number } | null {
  const sorted = [...snapshots]
    .filter((s) => parseIsoDate(s.date) && Number.isFinite(s.progressPercent))
    .sort((a, b) => a.date.localeCompare(b.date))
  if (sorted.length < 2) return null
  const early = sorted[0]
  const late = sorted[sorted.length - 1]
  const interval = calendarDaysBetween(early.date, late.date)
  if (interval == null || interval <= 0) return null
  const delta = late.progressPercent - early.progressPercent
  if (delta <= 0) return null
  return { rate: delta / interval, interval }
}

/**
 * Прогнозное влияние на срок по подтверждённому прогрессу и скорости.
 * При недостатке/противоречии входов — status: not_calculated.
 */
export function calculateScheduleImpact(inputs: ScheduleImpactInputs): ScheduleImpactResult {
  const methodId = SCHEDULE_IMPACT_METHOD_ID
  const methodVersion = SCHEDULE_IMPACT_METHOD_VERSION
  const dayType = inputs.dayType || 'calendar_days'
  const reasons: string[] = []

  if (dayType !== 'calendar_days') {
    reasons.push('Поддерживается только расчёт в календарных днях')
  }
  if (!parseIsoDate(inputs.plannedFinish)) reasons.push('Некорректная плановая дата завершения')
  if (!parseIsoDate(inputs.asOfDate)) reasons.push('Некорректная дата среза')
  if (!Number.isFinite(inputs.currentProgressPercent)) reasons.push('Нет подтверждённого текущего прогресса')
  else if (inputs.currentProgressPercent < 0 || inputs.currentProgressPercent > 100) {
    reasons.push('Текущий прогресс вне диапазона 0–100%')
  }

  let rate = inputs.dailyProgressPercentagePoints ?? null
  let rateSource: string = 'provided_daily_rate'
  let rateInterval: number | null = null

  if (rate == null || !Number.isFinite(rate) || rate <= 0) {
    const fromSnaps = rateFromSnapshots(inputs.progressSnapshots || [])
    if (fromSnaps) {
      rate = fromSnaps.rate
      rateInterval = fromSnaps.interval
      rateSource = 'difference_between_progress_snapshots'
    } else {
      reasons.push('Нет двух сопоставимых измерений прогресса или подтверждённой скорости')
    }
  }

  if (rate != null && rate <= 0) reasons.push('Скорость прогресса должна быть положительной')

  const planned = parseIsoDate(inputs.plannedFinish)
  const asOf = parseIsoDate(inputs.asOfDate)
  if (planned && asOf && asOf.getTime() > planned.getTime() + 366 * 86400000) {
    reasons.push('Дата среза слишком далеко от планового завершения — требуется проверка актуальности КСГ')
  }

  if (reasons.length || rate == null) {
    return {
      status: 'not_calculated',
      reasons: reasons.length ? reasons : ['Недостаточно данных для прогноза'],
      summaryRu: `Прогноз не рассчитан: ${(reasons.length ? reasons : ['недостаточно данных']).join('; ')}.`,
      methodId,
      methodVersion,
    }
  }

  const remaining = Math.max(0, 100 - inputs.currentProgressPercent)
  const remainingDays = Math.ceil(remaining / rate)
  const forecastFinish = addCalendarDays(inputs.asOfDate, remainingDays)
  const impactDays = calendarDaysBetween(inputs.plannedFinish, forecastFinish)
  if (impactDays == null) {
    return {
      status: 'not_calculated',
      reasons: ['Не удалось сопоставить даты прогноза и плана'],
      summaryRu: 'Прогноз не рассчитан: ошибка сравнения дат.',
      methodId,
      methodVersion,
    }
  }

  const sign = impactDays > 0 ? '+' : ''
  const summaryRu =
    impactDays === 0
      ? `Прогнозное завершение ${fmtRu(forecastFinish)} совпадает с планом ${fmtRu(inputs.plannedFinish)} (календарные дни).`
      : `Прогнозное влияние на срок: ${sign}${impactDays} календарных дней (план ${fmtRu(inputs.plannedFinish)} → прогноз ${fmtRu(forecastFinish)}).`

  return {
    status: 'calculated',
    plannedFinish: inputs.plannedFinish,
    asOfDate: inputs.asOfDate,
    forecastFinish,
    impactDays,
    dayType,
    currentProgressPercent: inputs.currentProgressPercent,
    remainingProgressPercent: remaining,
    dailyProgressPercentagePoints: rate,
    remainingDurationCalendarDays: remainingDays,
    methodId,
    methodVersion,
    calculationTrace: {
      inputs: {
        plannedFinish: inputs.plannedFinish,
        asOfDate: inputs.asOfDate,
        currentProgressPercent: inputs.currentProgressPercent,
        dailyProgressPercentagePoints: inputs.dailyProgressPercentagePoints ?? null,
        progressSnapshots: inputs.progressSnapshots || [],
        dayType,
      },
      rateSource,
      rateIntervalCalendarDays: rateInterval,
      formula:
        'remaining = 100 - currentProgress; remainingDays = ceil(remaining / dailyRate); forecastFinish = asOf + remainingDays; impactDays = forecastFinish - plannedFinish',
      methodId,
      methodVersion,
    },
    summaryRu,
  }
}
