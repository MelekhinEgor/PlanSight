/** Пользовательские подписи — внутренние коды API наружу не показываем. */

/** Демо-срез аналитики (график/статусы). Для загрузки снимков используйте defaultCaptureLocal(). */
export const AS_OF_ISO = '2026-09-17'

const MONTHS_SHORT = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']

/** Текущие дата/время в Europe/Moscow (без UTC-сдвига toISOString). */
export function moscowNowParts(now = new Date()): { date: string; hour: number; minute: number } {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/Moscow',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(now)
  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value || '00'
  return {
    date: `${get('year')}-${get('month')}-${get('day')}`,
    hour: Number(get('hour')),
    minute: Number(get('minute')),
  }
}

export function todayIsoMoscow(now = new Date()): string {
  return moscowNowParts(now).date
}

/** Подпись для шапки: «29 сен 2026». */
export function todayCaptionShort(isoDay?: string | null, now = new Date()): string {
  const day = isoDay && isoDay.length >= 10 ? isoDay.slice(0, 10) : todayIsoMoscow(now)
  const [y, m, d] = day.split('-')
  const mon = MONTHS_SHORT[Number(m) - 1] || m
  return `${Number(d)} ${mon} ${y}`
}

/** Предлагаемая дата/время съёмки — сейчас по Москве, минуты с шагом 5. */
export function defaultCaptureLocal(now = new Date()): string {
  const { date, hour, minute } = moscowNowParts(now)
  const mm = Math.floor(minute / 5) * 5
  return `${date}T${String(hour).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
}

export function fmtRuDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = iso.slice(0, 10)
  const [y, m, day] = d.split('-')
  if (!y || !m || !day) return iso
  return `${day}.${m}.${y}`
}

export function fmtRuDateTime(isoOrTs: string | null | undefined): string {
  if (!isoOrTs) return '—'
  const raw = String(isoOrTs).trim()
  const m = raw.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/)
  if (!m) {
    const t = Date.parse(raw)
    if (Number.isNaN(t)) return raw
    return new Date(t).toLocaleString('ru-RU', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Europe/Moscow',
    })
  }
  // Хранилище API — naive UTC (после перевода из Europe/Moscow). Показываем московское время.
  const hasTz = /[zZ]|[+-]\d{2}:?\d{2}$/.test(raw)
  const iso = hasTz ? raw : `${m[1]}T${m[2]}:${m[3]}:${m[4] || '00'}Z`
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return raw
  return new Date(t).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Europe/Moscow',
  })
}

const PROJECT_STATUS: Record<string, string> = {
  ON_TRACK: 'В норме',
  AT_RISK: 'Риск',
  DELAYED: 'Отставание',
  NO_DATA: 'Нет данных',
  COMPLETED: 'Завершён',
}

const ACTIVITY_STATE: Record<string, string> = {
  DELAYED: 'Отставание',
  AT_RISK: 'Риск',
  ON_TRACK: 'В работе',
  COMPLETED: 'Завершена',
  PLANNED_FUTURE: 'По плану',
  SHOULD_BE_ACTIVE: 'Должна идти',
}

const LIFECYCLE: Record<string, string> = {
  OPEN: 'Открыто',
  RESOLVED: 'Закрыто',
  ACKNOWLEDGED: 'Принято к проверке',
  SUPPRESSED: 'Скрыто',
  CLOSED: 'Закрыто',
}

const DEVIATION_CODE: Record<string, string> = {
  LOW_ACTIVITY: 'Низкая активность на камере',
  SCHEDULE_LAG: 'Отставание от графика',
  REQUIRED_EQUIPMENT_GAP: 'Нет ожидаемой техники',
  UNEXPECTED_EQUIPMENT_IN_ZONE: 'Неожиданная техника в зоне',
  AMBIGUOUS_ASSIGNMENT: 'Неоднозначная привязка',
  CAMERA_COVERAGE_GAP: 'Мало кадров для вывода',
  POSSIBLE_LATE_START: 'Возможный поздний старт',
  UNCONFIRMED_ACTIVITY: 'Активность не подтверждена',
  POSSIBLE_PAUSE: 'Возможный простой',
  WORK_AFTER_PLAN: 'Работы после планового срока',
  NEEDS_CAMERA_SETUP: 'Нужна настройка камеры',
  EARLY_START: 'Ранний старт',
}

const SIGNAL_KIND: Record<string, string> = {
  CV_VERIFIED_FINDING: 'По камерам',
  SYNTHETIC_DEMO_FINDING: 'По подготовленным наблюдениям',
  SCHEDULE_EDITORIAL: 'По графику',
  RISK_FROM_SCHEDULE: 'По графику',
  UNVERIFIED: 'Не подтверждено',
}

export function projectStatusRu(code: string | null | undefined): string {
  if (!code) return '—'
  return PROJECT_STATUS[code] ?? 'Статус уточняется'
}

export function activityStateRu(code: string | null | undefined): string {
  if (!code) return '—'
  return ACTIVITY_STATE[code] ?? 'По графику'
}

export function lifecycleRu(code: string | null | undefined): string {
  if (!code) return 'Открыто'
  return LIFECYCLE[code.toUpperCase()] ?? 'Открыто'
}

export function deviationCodeRu(code: string | null | undefined): string {
  if (!code) return 'Предупреждение по наблюдениям'
  return DEVIATION_CODE[code] ?? 'Предупреждение по наблюдениям'
}

export function signalKindRu(kind: string | null | undefined): string {
  if (!kind) return 'Сигнал'
  return SIGNAL_KIND[kind] ?? 'Сигнал'
}

export function asOfCaption(iso?: string | null): string {
  const day = iso && iso.length >= 10 ? iso.slice(0, 10) : todayIsoMoscow()
  return `Актуально на ${fmtRuDate(day)}`
}

/** Не показываем пользователю сырые технические идентификаторы в основном тексте. */
export function humanizeTechToken(raw: string | null | undefined): string {
  if (!raw) return '—'
  const s = String(raw)
  if (/^[A-Z0-9_.:-]{3,}$/.test(s) && /[A-Z]/.test(s) && s.includes('_')) {
    return DEVIATION_CODE[s] || SIGNAL_KIND[s] || 'служебный параметр'
  }
  return s
}

/** Ограничения карточки: убрать англ. служебные куски, если бэкенд ещё не успел. */
export function limitationRu(raw: string | null | undefined): string {
  if (!raw) return ''
  let s = String(raw).trim()
  const exact: Record<string, string> = {
    'без binding камера↔корпус назначение запрещено':
      'Без подтверждённой привязки камеры к корпусу назначение работы запрещено',
    'отсутствие кадров ≠ отсутствие техники на площадке':
      'Отсутствие кадров не означает отсутствие техники на площадке',
    'это возможный дефицит требуемой техники, не P(срыва сроков)':
      'Это возможный дефицит техники, а не оценка вероятности срыва сроков',
    'Не включать в production CV KPI': 'Не учитывать в рабочих показателях по камерам',
    'оценка по подтверждённой зоне корпуса, окно — последние часы до as_of':
      'Оценка по подтверждённой зоне корпуса; окно — последние часы до контрольной даты',
    'Оценка по подтверждённой зоне корпуса; окно — последние часы до as_of':
      'Оценка по подтверждённой зоне корпуса; окно — последние часы до контрольной даты',
  }
  if (exact[s]) return exact[s]
  const low = s.toLowerCase()
  for (const [k, v] of Object.entries(exact)) {
    if (k.toLowerCase() === low) return v
  }
  s = s
    .replace(/\bas[_\s-]?of\b/gi, 'контрольной даты')
    .replace(/\bbinding\b/gi, 'привязка')
    .replace(/\bproduction\s+CV\s+KPI\b/gi, 'рабочие показатели по камерам')
    .replace(/\bP\s*\(\s*срыва[^)]*\)/gi, 'оценка вероятности срыва сроков')
    .replace(/\buncalibrated[_\s-]?score\b/gi, 'некалиброванная оценка модели')
    .replace(/≠/g, ' не означает ')
    .replace(/\s{2,}/g, ' ')
    .replace(/\s([,;.])/g, '$1')
    .trim()
  return s
}

export function limitationsRu(items: Array<string | null | undefined> | null | undefined): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const x of items || []) {
    const t = limitationRu(x)
    if (!t || seen.has(t)) continue
    seen.add(t)
    out.push(t)
  }
  return out
}
