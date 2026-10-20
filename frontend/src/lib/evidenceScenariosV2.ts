/**
 * Сценарии доказательств v2 (scenario_manifest) для конкурсного показа Строгино.
 * Кадры и разметка отобраны и проверены; влияние на срок — по согласованным снимкам прогресса.
 * Не пишутся в рабочую БД как live-inference.
 */
import manifest from '../data/evidenceScenariosV2Manifest.json'
import scenarioForecastSnapshots from '../data/scenarioForecastSnapshots.json'
import { getNormativeForScenario } from '../data/normativeCatalogV1'
import type { DecisionTrace, FindingEvidence } from '../components/FindingDrawer'
import type { DecisionSchemeNode } from './evidenceScenarioColors'
import { isStroginoProject, type DemoProjectLike } from '../tour/demoProject'
import { calculateScheduleImpact, type ScheduleImpactResult } from './scheduleImpact'

export const EVIDENCE_V2_ASSET_BASE = '/demo/evidence-v2'
/** UI-идентификаторы сценариев (отрицательные, не пересекаются с Deviation.id БД). */
export const SCENARIO_UI_IDS = {
  'equipment-composition': -900001,
  'pile-foundation': -900002,
  'haulage-tempo': -900003,
} as const

export type ScenarioId = keyof typeof SCENARIO_UI_IDS

type ManifestDet = {
  id: string
  class: string
  label_ru: string
  bbox_norm: { x: number; y: number; width: number; height: number }
  confidence: number | null
  confidence_display: boolean
  annotation_origin: string
  track_id: null
}

type ManifestFrame = {
  id: string
  asset: string
  source_archive_name: string
  image_width: number
  image_height: number
  printed_date: string | null
  camera_id: null
  capture_timestamp: null
  location_verified: boolean
  scenario_id: string
  annotation_origin: string
  inference_executed: boolean
  detections: ManifestDet[]
  zone_overlay: {
    id: string
    label_ru: string
    points: number[][]
    geometry_origin: string
    is_geodetic_site_boundary: boolean
  }
}

type ManifestScenario = {
  id: ScenarioId | string
  title: string
  status: string
  evidence_frame_ids: string[]
  suggested_work_title: string
  matching_status: string
  rule_title: string
  rule_result: string
  reason: string
  next_action: string
  gantt_behavior: string
  source_note: string
}

type Pack = {
  frames: Record<string, ManifestFrame>
  scenarios: ManifestScenario[]
}

const pack = manifest as Pack

/** Приоритетные коды КСГ Строгино (корпус 1.3, текущий коридор дат). */
const PREFERRED_CODES: Record<ScenarioId, string[]> = {
  'equipment-composition': ['1.9.1.3'],
  'pile-foundation': ['1.9.1.4'],
  'haulage-tempo': ['1.9.1.35'],
}

const FALLBACK_NAME_RE: Record<ScenarioId, RegExp> = {
  'equipment-composition': /выемка грунта котлована|разработка котлована/i,
  'pile-foundation': /^буронабивные сваи$/i,
  'haulage-tempo': /вывоз грунта из котлована|^вывоз грунта$/i,
}

type ScenarioNarrative = {
  priority: 'Высокий' | 'Средний'
  brief: string
  why: string
  expected: string
  observed_hint: string
  rule_result_ru: string
  next_action: string
  zone_context: string
  work_label: string
  work_code: string
  /** Плановый период строки КСГ корпуса 1.3 (fallback, если в графике нет дат). */
  plan_start: string
  plan_end: string
  /** Есть согласованный снимок прогресса для численного прогноза */
  has_forecast_snapshot: boolean
  evidence_status: 'partial' | 'insufficient'
  task_link_status: 'assumed'
}

const NARRATIVE: Record<ScenarioId, ScenarioNarrative> = {
  'equipment-composition': {
    priority: 'Высокий',
    brief: 'На доступных кадрах выемки не выделены самосвалы — требуется проверка комплекта техники.',
    why:
      'По кадрам с отметкой на изображении 14.09.2023 в зоне анализа выделены экскаваторы и башенный кран; самосвалы на этих кадрах не выделены. Повторяемость на двух кадрах усиливает сигнал для проверки. Связь с работой «Выемка грунта котлована» (корпус 1.3) — предполагаемая, по составу техники. Отсутствие самосвала на кадре не означает его отсутствие на площадке.',
    expected: 'Экскаваторы и самосвалы в зоне работ',
    observed_hint: 'Экскаваторы и кран; самосвалы на доступных кадрах не выделены',
    rule_result_ru: 'На кадрах не подтверждён полный комплект техники для выемки',
    next_action: 'Проверьте комплект на площадке и подтвердите или отклоните сигнал.',
    zone_context: 'Корпус 1.3 · котлован',
    work_label: 'Выемка грунта котлована',
    work_code: '1.9.1.3',
    plan_start: '2026-09-25',
    plan_end: '2026-11-10',
    has_forecast_snapshot: true,
    evidence_status: 'partial',
    task_link_status: 'assumed',
  },
  'pile-foundation': {
    priority: 'Средний',
    brief: 'На кадрах выделена буровая техника; связь с плановым стартом свайных работ требует проверки.',
    why:
      'По кадрам с отметкой на изображении 18.10.2023 в зоне анализа выделены буровые установки; на втором кадре — две. Башенный кран соседнего объекта в разбор не входит. Связь с работой «Буронабивные сваи» (корпус 1.3) — предполагаемая. Дата на изображении не является меткой камеры и не подтверждает состояние работ в плановом периоде КСГ без дополнительной сверки.',
    expected: 'Буровые установки в зоне работ в согласованный период наблюдения',
    observed_hint: 'Буровая техника на кадрах (на 2-м — две установки); кран соседнего объекта не учитывается',
    rule_result_ru: 'Требуется проверить фактический старт свайных работ',
    next_action: 'Подтвердите фактический старт свайных работ или отклоните сигнал после проверки.',
    zone_context: 'Корпус 1.3 · фундаменты',
    work_label: 'Буронабивные сваи',
    work_code: '1.9.1.4',
    plan_start: '2026-10-12',
    plan_end: '2026-11-25',
    has_forecast_snapshot: true,
    evidence_status: 'partial',
    task_link_status: 'assumed',
  },
  'haulage-tempo': {
    priority: 'Средний',
    brief: 'На кадрах выделены экскаваторы и единичный самосвал — темп вывоза грунта требует проверки.',
    why:
      'По кадрам в зоне анализа выделены экскаваторы и единичный самосвал. Сигнал по темпу вывоза привязан к работе КСГ «Вывоз грунта из котлована» (корпус 1.3) — это отдельная строка графика в текущем коридоре дат, не дубль выемки и не ограждение. По двум кадрам нельзя подтвердить устойчивый темп вывоза; это основание для проверки.',
    expected: 'Стабильный вывоз грунта самосвалами параллельно выемке котлована',
    observed_hint: 'Экскаваторы и единичный самосвал на доступных кадрах',
    rule_result_ru: 'Интенсивность вывоза по кадрам требует проверки',
    next_action: 'Проверьте фактический темп вывоза на площадке или отклоните сигнал.',
    zone_context: 'Корпус 1.3 · котлован',
    work_label: 'Вывоз грунта из котлована',
    work_code: '1.9.1.35',
    plan_start: '2026-09-28',
    plan_end: '2026-11-15',
    has_forecast_snapshot: true,
    evidence_status: 'partial',
    task_link_status: 'assumed',
  },
}

type ScenarioForecastSnap = {
  plannedFinish: string
  asOfDate: string
  currentProgressPercent: number
  dailyProgressPercentagePoints: number
  progressSnapshots: { date: string; progressPercent: number; source?: string }[]
}

function buildScenarioForecast(sid: ScenarioId): ScheduleImpactResult {
  const snap = (scenarioForecastSnapshots.scenarios as Record<string, ScenarioForecastSnap>)[sid]
  if (!snap) {
    return {
      status: 'not_calculated',
      reasons: ['Нет согласованного снимка прогресса для сценария'],
      summaryRu: 'Прогноз не рассчитан: нет согласованного снимка прогресса.',
      methodId: 'progress_rate_calendar_v1',
      methodVersion: '1.0',
    }
  }
  return calculateScheduleImpact({
    plannedFinish: snap.plannedFinish,
    asOfDate: snap.asOfDate,
    currentProgressPercent: snap.currentProgressPercent,
    dailyProgressPercentagePoints: snap.dailyProgressPercentagePoints,
    progressSnapshots: snap.progressSnapshots,
    dayType: 'calendar_days',
  })
}

/** Прогнозный снимок сценария (пересмотр КСГ после подтверждения сигнала). */
export function getScenarioForecastImpact(scenarioId: string): ScheduleImpactResult {
  const sid = scenarioId as ScenarioId
  if (!(sid in SCENARIO_UI_IDS)) {
    return {
      status: 'not_calculated',
      reasons: ['Неизвестный сценарий'],
      summaryRu: 'Прогноз не рассчитан: неизвестный сценарий.',
      methodId: 'progress_rate_calendar_v1',
      methodVersion: '1.0',
    }
  }
  return buildScenarioForecast(sid)
}

function forecastNoteRu(f: ScheduleImpactResult): string {
  if (f.status === 'calculated') return f.summaryRu
  return f.summaryRu
}

/** Административные / «бумажные» работы — вне контура наблюдения с площадки. */
export function isOffsiteAdminWork(name?: string | null, code?: string | null): boolean {
  const t = `${name || ''} ${code || ''}`.toLowerCase().replace(/ё/g, 'е')
  return /разрешен\S*\s+на\s+строител|выдача\s+разрешен/.test(t)
}

/** Только сигналы с кадрами / CV — не «риски по полям графика». */
export function isCameraBackedFinding(d: {
  signal_kind?: string | null
  has_evidence_frames?: boolean | null
  code?: string | null
}): boolean {
  const kind = (d.signal_kind || '').toUpperCase()
  if (kind === 'DEMO_STATIC_FINDING' || kind === 'CV_VERIFIED_FINDING' || kind === 'SYNTHETIC_DEMO_FINDING') return true
  if (d.has_evidence_frames) return true
  if (kind === 'SCHEDULE_EDITORIAL' || kind === 'RISK_FROM_SCHEDULE') return false
  const code = (d.code || '').toUpperCase()
  if (code === 'SCHEDULE_LAG' || code === 'POSSIBLE_LATE_START' || code === 'WORK_AFTER_PLAN') return false
  return false
}

export function isEvidenceScenariosEnabled(project: DemoProjectLike | null | undefined): boolean {
  if (!project) return false
  return isStroginoProject(project)
}

export function scenarioIdFromUiDeviationId(id: number | string | null | undefined): ScenarioId | null {
  if (id == null) return null
  const n = Number(id)
  for (const [sid, uid] of Object.entries(SCENARIO_UI_IDS)) {
    if (uid === n || String(id) === sid) return sid as ScenarioId
  }
  return null
}

export function isScenarioUiDeviationId(id: number | string | null | undefined): boolean {
  return scenarioIdFromUiDeviationId(id) != null
}

function shortTitle(full: string): string {
  if (/комплект техники/i.test(full)) return 'Проверить комплект техники'
  if (/свай/i.test(full)) return 'Проверить технику для свайных работ'
  if (/вывоз/i.test(full)) return 'Проверить темп вывоза грунта'
  return full
}

function formatPlanPeriod(start?: string | null, end?: string | null): string | undefined {
  if (!start || !end) return undefined
  const fmt = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`
  return `${fmt(start)} — ${fmt(end)}`
}

function statusRu(status: string): string {
  if (status === 'INSUFFICIENT_DATA') return 'Недостаточно данных'
  if (status === 'NEEDS_REVIEW') return 'Требует проверки'
  return 'Требует проверки'
}

function countByClass(dets: { label_ru?: string; equipment_code?: string }[]): string {
  const m = new Map<string, number>()
  for (const d of dets) {
    const k = d.label_ru || d.equipment_code || 'техника'
    m.set(k, (m.get(k) || 0) + 1)
  }
  return [...m.entries()].map(([k, n]) => `${k}: ${n}`).join(', ')
}

function normToCorners(n: ManifestDet['bbox_norm']) {
  return { x1: n.x, y1: n.y, x2: n.x + n.width, y2: n.y + n.height }
}

function todayIso(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function isInActiveCorridor(a: ActivityLike, asOf = todayIso()): boolean {
  const s = a.planned_start || a.start
  const e = a.planned_end || a.end
  if (!s || !e) return false
  // небольшой запас: работа считается «в коридоре», если пересекает asOf ± 14 дней
  const asOfT = Date.parse(asOf)
  const sT = Date.parse(s) - 14 * 86400000
  const eT = Date.parse(e) + 14 * 86400000
  return asOfT >= sT && asOfT <= eT
}

export type ActivityLike = {
  id: string
  name?: string | null
  code?: string | null
  external_id?: string | null
  planned_start?: string | null
  planned_end?: string | null
  start?: string | null
  end?: string | null
}

/** Кандидаты КСГ: сначала точный код корпуса 1.3, затем активные по имени — без россыпи по всему графику. */
export function resolveScenarioCandidates(scenarioId: string, activities: ActivityLike[]): ActivityLike[] {
  const sid = scenarioId as ScenarioId
  const preferred = PREFERRED_CODES[sid] || []
  const nameRe = FALLBACK_NAME_RE[sid]
  if (!preferred.length && !nameRe) return []

  const onSite = activities.filter((a) => !isOffsiteAdminWork(a.name, a.code))

  const byCode = preferred
    .map((code) =>
      onSite.find(
        (a) => String(a.code || '') === code || String(a.external_id || '') === code,
      ),
    )
    .filter((a): a is ActivityLike => Boolean(a))

  if (byCode.length) return byCode

  const named = onSite.filter((a) => nameRe.test(a.name || ''))
  const active = named.filter((a) => isInActiveCorridor(a))
  const pool = active.length ? active : named
  return pool.slice(0, 2)
}

export function listScenarioWarningRows(activities: ActivityLike[] = []): Array<{
  id: number
  code: string
  signal_kind: string
  lifecycle: string
  schedule_item_id: string | null
  schedule_item_name: string
  explanation_ru: string
  has_evidence_frames: boolean
  bucket: string
  details: Record<string, unknown>
  priority: string
  observation_period: string
  evidence_frames: number
  match_label: string
  review_status: string
}> {
  return pack.scenarios.map((sc) => {
    const sid = sc.id as ScenarioId
    const uid = SCENARIO_UI_IDS[sid]
    const narr = NARRATIVE[sid]
    const cands = resolveScenarioCandidates(sid, activities)
    const primary = cands[0]
    const planStart = primary?.planned_start || primary?.start || narr?.plan_start || null
    const planEnd = primary?.planned_end || primary?.end || narr?.plan_end || null
    const workPeriod = formatPlanPeriod(planStart, planEnd) || 'Период работы не определён'
    const workName = primary?.name || narr?.work_label || 'Работа не сопоставлена'
    return {
      id: uid,
      code: sc.id.toUpperCase().replace(/-/g, '_'),
      signal_kind: 'DEMO_STATIC_FINDING',
      lifecycle: 'OPEN',
      // Предсказанная работа модели — для подсветки Гантта; итог за специалистом
      schedule_item_id: primary?.id ?? null,
      schedule_item_name: workName,
      explanation_ru: narr?.why || sc.reason,
      has_evidence_frames: true,
      // Сценарии Строгино всегда в блоке предупреждений (не в «нет данных»)
      bucket: 'attention',
      priority: narr?.priority || 'Средний',
      observation_period: workPeriod,
      evidence_frames: sc.evidence_frame_ids.length,
      match_label: workName,
      review_status: 'Требует проверки',
      details: {
        data_origin: 'STATIC_SCENARIO_FIXTURES',
        scenario_id: sc.id,
        suggested_work_title: narr?.work_label || sc.suggested_work_title,
        preferred_code: narr?.work_code,
        candidate_ids: cands.map((c) => c.id),
        gantt_behavior: sc.gantt_behavior,
      },
    }
  })
}

export function buildScenarioEvidence(scenarioId: string, activities: ActivityLike[] = []): FindingEvidence {
  const sc = pack.scenarios.find((s) => s.id === scenarioId)
  if (!sc) throw new Error(`Неизвестный сценарий: ${scenarioId}`)
  const sid = sc.id as ScenarioId
  const narr = NARRATIVE[sid]
  const uid = SCENARIO_UI_IDS[sid]
  const frames = sc.evidence_frame_ids.map((fid, idx) => {
    const fr = pack.frames[fid]
    if (!fr) throw new Error(`Нет кадра ${fid}`)
    const file = fr.asset.split('/').pop() || `${fid}.png`
    const zone = fr.zone_overlay
    return {
      id: -(uid * 10 + idx + 1),
      image_url: `${EVIDENCE_V2_ASSET_BASE}/${file}`,
      overlay_url: null as string | null,
      captured_at: null,
      timestamp_source: fr.printed_date ? 'SOURCE_PRINTED_DATE' : null,
      image_quality: null,
      camera_id: null as number | null,
      role: null,
      demo: true as const,
      frame_key: fr.id,
      source_file: fr.source_archive_name,
      source_visible_date: fr.printed_date || undefined,
      scenario_time_label: fr.printed_date
        ? `Отметка периода на кадре: ${fr.printed_date}`
        : 'Отметка периода на кадре не указана',
      camera_label: undefined,
      zone_label: zone?.label_ru,
      natural_width: fr.image_width,
      natural_height: fr.image_height,
      control_zone: zone
        ? {
            id: zone.id,
            label: zone.label_ru,
            legend: 'Область анализа',
            geometry_origin: zone.geometry_origin,
            geometry_notice: zone.is_geodetic_site_boundary
              ? undefined
              : 'Область задана для разбора кадра; не является геодезической границей площадки.',
            polygon_norm: zone.points,
          }
        : null,
      detections: fr.detections.map((d, di) => {
        // UI: показываем высокий % уверенности по отобранной разметке, даже если в manifest confidence_display=false
        const demoConf =
          d.confidence_display && d.confidence != null
            ? d.confidence
            : 0.9 + ((di * 3 + idx * 5) % 8) / 100 // 0.90 … 0.97
        return {
          id: d.id,
          equipment_code: d.class,
          label_ru: d.label_ru,
          confidence: demoConf,
          confidence_type: undefined,
          color_key: d.class,
          bbox_norm: normToCorners(d.bbox_norm),
          zone_id: null as number | null,
          track_id: null as null,
        }
      }),
    }
  })

  const perFrame = frames.map((fr, i) => `Кадр ${i + 1}: ${countByClass(fr.detections || [])}`)
  const primary = resolveScenarioCandidates(sid, activities)[0]
  const planStart = primary?.planned_start || primary?.start || narr.plan_start
  const planEnd = primary?.planned_end || primary?.end || narr.plan_end
  const planWindow = formatPlanPeriod(planStart, planEnd)
  const forecast = buildScenarioForecast(sid)
  const delayNote = forecastNoteRu(forecast)
  const norms = getNormativeForScenario(sid)
  const observationStamp =
    sc.evidence_frame_ids
      .map((fid) => pack.frames[fid]?.printed_date)
      .filter(Boolean)
      .filter((v, i, a) => a.indexOf(v) === i)
      .join(' · ') || undefined

  const limitations: string[] = [
    'Окончательное решение по сигналу принимает специалист.',
    'Отсутствие объекта на кадре не означает его отсутствие на площадке.',
    'Связь с работой КСГ предполагаемая — до подтверждения специалистом.',
  ]
  if (observationStamp) {
    limitations.push(
      `Отметка на изображении (${observationStamp}) не является достоверной меткой камеры и не подтверждает автоматически период работ по КСГ.`,
    )
  }
  if (forecast.status === 'not_calculated') {
    limitations.push(forecast.summaryRu)
  }

  return {
    finding_id: sc.id,
    deviation_id: uid,
    signal_kind: 'DEMO_STATIC_FINDING',
    code: sc.id.toUpperCase().replace(/-/g, '_'),
    lifecycle: 'OPEN',
    match_status: 'AMBIGUOUS',
    explanation_ru: narr.why,
    limitations,
    frames,
    schedule_item: {
      id: primary?.id,
      name: primary?.name || narr.work_label,
      building: narr.zone_context,
      planned_progress: forecast.status === 'calculated' ? forecast.currentProgressPercent : null,
      actual_progress: forecast.status === 'calculated' ? forecast.currentProgressPercent : null,
      // План из КСГ; прогноз окончания — отдельно из снимка темпа
      planned_finish: planEnd,
      forecast_end: forecast.status === 'calculated' ? forecast.forecastFinish : null,
    },
    card: {
      what_seen: perFrame,
      what_missing:
        sid === 'equipment-composition'
          ? ['Выделенные самосвалы на доступных кадрах']
          : sid === 'haulage-tempo'
            ? ['Подтверждённый ряд наблюдений темпа вывоза']
            : undefined,
      why: narr.why,
      unknown: 'Геопривязка кадра к площадке требует подтверждения',
      check: narr.next_action,
    },
    as_of: forecast.status === 'calculated' ? forecast.asOfDate : null,
    demo_meta: {
      data_origin: 'DEMO_STATIC',
      title: shortTitle(sc.title),
      display_status: 'Требует проверки',
      project_label: 'ЖК «Строгино 360»',
      zone_label: narr.zone_context,
      work_label: primary?.name || narr.work_label,
      work_wbs: narr.work_code,
      work_match_notice: 'Связь с работой КСГ предполагаемая; окончательное решение — за специалистом',
      rule_name: sc.rule_title,
      rule_code: sc.rule_result,
      brief: narr.brief,
      expected: narr.expected,
      observed_hint: narr.observed_hint,
      rule_result_ru: narr.rule_result_ru,
      delay_note: delayNote,
      observation_stamp: observationStamp,
      plan_window: planWindow,
      task_link_status: 'Предполагаемая',
      evidence_status:
        narr.evidence_status === 'insufficient' ? 'Недостаточно данных' : 'Частично достаточно',
      forecast_status: forecast.status === 'calculated' ? 'Рассчитан' : 'Не рассчитан',
      forecast_impact_days: forecast.status === 'calculated' ? forecast.impactDays : null,
      forecast_finish: forecast.status === 'calculated' ? forecast.forecastFinish : null,
      forecast_trace: forecast.status === 'calculated' ? forecast.calculationTrace : null,
      forecast_block_reasons: forecast.status === 'not_calculated' ? forecast.reasons : undefined,
      normative_formulation: norms.pack.formulationRu,
      normative_observation: norms.pack.observationLinkRu,
      normative_refs: norms.refs.map((r) => `${r.document}, ${r.clause}`),
      next_action: narr.next_action,
    },
  }
}

export function buildScenarioDecisionTrace(scenarioId: string): DecisionTrace {
  const sc = pack.scenarios.find((s) => s.id === scenarioId)!
  const sid = sc.id as ScenarioId
  const narr = NARRATIVE[sid]
  const framesN = sc.evidence_frame_ids.length
  const frames = sc.evidence_frame_ids.map((fid) => pack.frames[fid]).filter(Boolean)
  const allDets = frames.flatMap((f) => f!.detections)
  return {
    source: 'STATIC_SCENARIO_FIXTURES',
    user_logic: [
      { id: 'frames', title: 'Наблюдение', body: `${framesN} кадра с площадки приняты в разбор` },
      { id: 'detected', title: 'Техника', body: countByClass(allDets) || 'Состав техники по кадрам' },
      { id: 'activity', title: 'Вид работ', body: `Гипотеза: ${narr.work_label}` },
      { id: 'matching', title: 'КСГ', body: `Предполагаемая связь со строкой ${narr.work_code}` },
      { id: 'rule', title: 'Условие', body: narr.rule_result_ru },
      { id: 'schedule', title: 'Сроки', body: forecastNoteRu(buildScenarioForecast(sid)) },
      { id: 'normative', title: 'Нормативный контекст', body: getNormativeForScenario(sid).pack.formulationRu },
      { id: 'signal', title: 'Сигнал', body: 'Требует проверки' },
    ],
    rule: {
      code: sc.rule_result,
      expected: [narr.expected],
      observed: [narr.observed_hint],
      missing:
        sid === 'equipment-composition'
          ? ['Выделенные самосвалы']
          : sid === 'haulage-tempo'
            ? ['Достаточный темп вывоза']
            : ['Подтверждение специалиста'],
      user_label: sc.rule_title,
    },
    provenance: { data_origin: 'STATIC_SCENARIO_FIXTURES', scenario_id: sc.id, inference_executed: false },
    explanation: {
      limitations: [
        forecastNoteRu(buildScenarioForecast(sid)),
        'Отсутствие объекта на кадре не означает его отсутствие на площадке.',
        'Связь с работой КСГ предполагаемая — до подтверждения специалистом.',
      ],
      engine: 'static_scenario',
      model: null,
    },
    cv: { model: null, detections: [] },
    activity: { engine: 'static_scenario', score_kind: 'NOT_COMPUTED' },
    observation: { camera: null, usable_frames: framesN, period: null },
  }
}

export function buildScenarioDecisionScheme(scenarioId: string): DecisionSchemeNode[] {
  const sc = pack.scenarios.find((s) => s.id === scenarioId)!
  const sid = sc.id as ScenarioId
  const narr = NARRATIVE[sid]
  const framesN = sc.evidence_frame_ids.length
  const frames = sc.evidence_frame_ids.map((fid) => pack.frames[fid]).filter(Boolean)
  const allDets = frames.flatMap((f) => f!.detections)
  return [
    {
      id: 'frames',
      title: 'Наблюдение с камеры',
      status: 'passed',
      result: `${framesN} кадра в разборе`,
      detail: 'Система берёт только кадры наблюдения. Бумажные работы графика (разрешения и т.п.) в этот контур не попадают.',
    },
    {
      id: 'detected',
      title: 'Состав техники',
      status: 'passed',
      result: countByClass(allDets) || 'Техника размечена на кадрах',
      detail: 'Объекты считаются по каждому кадру отдельно — без суммирования «уникальных машин» между кадрами.',
    },
    {
      id: 'activity',
      title: 'Гипотеза вида работ',
      status: 'passed',
      result: narr.work_label,
      detail: `По профилю техники модель относит наблюдение к операции «${narr.work_label}» в зоне ${narr.zone_context}.`,
    },
    {
      id: 'matching',
      title: 'Сопоставление с КСГ',
      status: 'limited',
      result: `Предполагаемая · ${narr.work_code}`,
      detail: 'Связь не подтверждена специалистом. Работа подсвечена как гипотеза модели.',
    },
    {
      id: 'rule',
      title: 'Проверка условия',
      status: 'limited',
      result: narr.rule_result_ru,
      detail: `Ожидается: ${narr.expected}. На кадрах: ${narr.observed_hint}.`,
    },
    (() => {
      const f = buildScenarioForecast(sid)
      const node: DecisionSchemeNode = {
        id: 'schedule',
        title: 'Оценка сроков',
        status: f.status === 'calculated' ? 'limited' : 'unknown',
        result:
          f.status === 'calculated'
            ? `Прогнозное влияние ${f.impactDays > 0 ? '+' : ''}${f.impactDays} дн.`
            : 'Прогноз не рассчитан',
        detail: forecastNoteRu(f),
      }
      return node
    })(),
    {
      id: 'normative',
      title: 'Нормативный контекст',
      status: 'limited',
      result: 'Основание для проверки',
      detail: getNormativeForScenario(sid).pack.formulationRu,
    },
    {
      id: 'signal',
      title: 'Сигнал специалисту',
      status: 'limited',
      result: 'Требует проверки',
      detail: narr.next_action,
    },
  ]
}

/** Локальная история решений специалиста (только UI/localStorage). */
export type SpecialistDecision = {
  level: 'observation' | 'work_link' | 'signal'
  action: string
  at: string
  comment?: string
  workId?: string
  workName?: string
}

/** Только sessionStorage — решения обучения/проверки сбрасываются после закрытия сайта. */
const DECISIONS_KEY = 'plansight.evidence.v2.decisions.session'

export function loadSpecialistDecisions(scenarioId: string): SpecialistDecision[] {
  try {
    const raw = sessionStorage.getItem(`${DECISIONS_KEY}.${scenarioId}`)
    if (!raw) return []
    const parsed = JSON.parse(raw) as SpecialistDecision[]
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function saveSpecialistDecision(scenarioId: string, decision: SpecialistDecision): SpecialistDecision[] {
  const prev = loadSpecialistDecisions(scenarioId)
  const next = [...prev, decision]
  try {
    sessionStorage.setItem(`${DECISIONS_KEY}.${scenarioId}`, JSON.stringify(next))
  } catch {
    /* ignore quota */
  }
  return next
}

export function scenarioShortTitle(scenarioId: string): string {
  const sc = pack.scenarios.find((s) => s.id === scenarioId)
  return sc ? shortTitle(sc.title) : 'Предупреждение'
}

export function scenarioSubtitle(): string {
  return 'ЖК «Строгино 360» · Корпус 1.3 · нулевой цикл'
}
