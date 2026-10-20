import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { equipmentRu } from '../labels/equipment'
import {
  activityStateRu,
  asOfCaption,
  deviationCodeRu,
  fmtRuDate,
  fmtRuDateTime,
  lifecycleRu,
  limitationsRu,
  signalKindRu,
} from '../labels/ru'
import {
  demoClassColor,
  schemeFromDecisionTrace,
  stroginoDemoSubtitle,
  type DecisionSchemeNode,
} from '../lib/stroginoDemoFrames'
import {
  buildScenarioDecisionScheme,
  getScenarioForecastImpact,
  loadSpecialistDecisions,
  saveSpecialistDecision,
  scenarioIdFromUiDeviationId,
  type SpecialistDecision,
} from '../lib/evidenceScenariosV2'
import { loadSessionScheduleRevision, type ScheduleRevisionResult } from '../lib/scheduleRevision'
import { registerTourBridge } from '../tour/tourBridge'
import { WorkCompletePanel } from './WorkCompletePanel'
import { EvidenceFrameView, preloadEvidenceImages } from './EvidenceFrameView'

function matchStatusRu(status?: string | null): string {
  const s = (status || '').toUpperCase()
  if (s === 'ACCEPTED') return 'Подтверждено'
  if (s === 'AMBIGUOUS' || s === 'DEMO_SIMULATED') return 'Связь неоднозначна'
  if (s === 'REJECTED') return 'Отклонено'
  if (s === 'UNMATCHED') return 'Работа не сопоставлена'
  return status || 'Не определён'
}

const TRACE_TOUR_ID: Record<string, string> = {
  observation: 'finding-trace-source',
  frames: 'finding-trace-source',
  detected: 'finding-trace-detection',
  activity: 'finding-trace-activity',
  matching: 'finding-trace-matching',
  rule: 'finding-trace-rule',
  schedule: 'finding-trace-schedule',
  normative: 'finding-trace-normative',
  work: 'finding-trace-activity',
  signal: 'finding-trace-signal',
  zone: 'finding-trace-zone',
  quality: 'finding-trace-source',
}

export type FindingEvidence = {
  finding_id?: string | null
  deviation_id?: number | null
  signal_kind?: string
  code?: string
  lifecycle?: string | null
  /** ACCEPTED | AMBIGUOUS | REJECTED | UNMATCHED — КСГ как факт только при ACCEPTED */
  match_status?: string | null
  explanation_ru?: string
  limitations?: string[]
  frames?: {
    id: number
    image_url?: string
    overlay_url?: string | null
    captured_at?: string | null
    timestamp_source?: string | null
    image_quality?: string | null
    camera_id?: number | null
    role?: string | null
    demo?: boolean
    frame_key?: string
    source_file?: string
    source_visible_date?: string
    scenario_time_label?: string
    camera_label?: string
    zone_label?: string
    natural_width?: number
    natural_height?: number
    control_zone?: {
      id?: string
      label: string
      legend?: string
      geometry_origin?: string
      geometry_notice?: string
      polygon_norm: number[][]
    } | null
    detections?: {
      id?: string
      equipment_code?: string
      label_ru?: string
      confidence?: number
      confidence_type?: string
      color_key?: string
      bbox_norm?: { x1: number; y1: number; x2: number; y2: number }
      zone_id?: number | null
      track_id?: null
    }[]
  }[]
  schedule_item?: {
    id?: string
    name?: string
    building?: string | null
    planned_progress?: number | null
    actual_progress?: number | null
    planned_finish?: string | null
    forecast_end?: string | null
  } | null
  card?: { what_seen?: string[]; what_missing?: string[]; why?: string | null; unknown?: string | null; check?: string | null }
  as_of?: string | null
  verdict_history?: {
    id?: number
    verdict?: string
    user_id?: string
    created_at?: string | null
    is_ml_label?: boolean
  }[]
  last_verdict?: string | null
  demo_meta?: {
    data_origin: 'DEMO_STATIC'
    title: string
    display_status: string
    project_label: string
    zone_label: string
    work_label: string
    work_wbs: string
    work_match_notice: string
    source_notice?: string
    rule_name: string
    rule_code: string
    brief?: string
    expected?: string
    observed_hint?: string
    rule_result_ru?: string
    delay_note?: string
    plan_window?: string
    observation_stamp?: string
    task_link_status?: string
    evidence_status?: string
    forecast_status?: string
    forecast_impact_days?: number | null
    forecast_finish?: string | null
    forecast_trace?: Record<string, unknown> | null
    forecast_block_reasons?: string[]
    normative_formulation?: string
    normative_observation?: string
    normative_refs?: string[]
    next_action?: string
  }
}

export type DecisionTrace = {
  source?: string
  user_logic?: { id: string; title: string; body: string }[]
  rule?: { code?: string; expected?: string[]; observed?: string[]; missing?: string[]; user_label?: string }
  provenance?: Record<string, unknown>
  expert?: { frame_ids?: number[]; details?: Record<string, unknown> }
  observation?: { camera?: { name?: string } | null; usable_frames?: number; period?: string | null } | null
  cv?: { model?: { name?: string } | null; detections?: unknown[] } | null
  activity?: { engine?: string; score_kind?: string } | null
  explanation?: { limitations?: string[]; engine?: string; model?: string | null }
}

type Props = {
  open: boolean
  onClose: () => void
  title: string
  subtitle?: string
  loading?: boolean
  evidence: FindingEvidence | null
  decisionTrace?: DecisionTrace | null
  decisionTraceLoading?: boolean
  error?: string | null
  onRetry?: () => void
  variant?: 'overlay' | 'inline'
  editorial?: {
    title: string
    text: string
    expected: string
    detected: string
    rule: string
    asOf: string
    plan?: number
    fact?: number
    plannedEnd?: string | null
    forecastEnd?: string | null
    state?: string
  } | null
  commentsSlot?: ReactNode
  onAcknowledge?: () => void
  acknowledgeBusy?: boolean
  onVerdict?: (verdict: 'confirm' | 'reject' | 'correct', correction?: Record<string, unknown>) => void
  verdictBusy?: boolean
  onReopen?: () => void
  reopenBusy?: boolean
  onVlmAssist?: () => void
  vlmBusy?: boolean
  vlmText?: string | null
  projectId?: string
  /** Сформировать отчёт Word по карточке */
  onExport?: () => void
  exportBusy?: boolean
  /** Кандидаты КСГ при неоднозначном сопоставлении */
  workCandidates?: { id: string; name: string }[]
  confirmedWorkId?: string | null
  onConfirmWorkLink?: (workId: string, workName: string) => void
  onRejectWorkLink?: () => void
  /**
   * После подтверждения сигнала — пересчёт прогноза КСГ (what-if).
   * Родитель применяет патчи к графику и возвращает итог для панели влияния.
   */
  onConfirmSignal?: (ctx: {
    scenarioId: string | null
    workId: string | null
    workName?: string | null
  }) => ScheduleRevisionResult | null | void
}

type LayerMode = 'all' | 'equipment' | 'zone'

function signalRu(kind?: string) {
  return signalKindRu(kind)
}

function isRealConfidence(d: { confidence?: number; confidence_type?: string } | undefined): boolean {
  if (d?.confidence == null) return false
  return d.confidence_type !== 'SIMULATED_DEMO_VALUE'
}

function observationLine(frames: FindingEvidence['frames']): string {
  if (!frames?.length) return 'Нет кадров'
  return frames
    .map((fr, i) => {
      const dets = fr.detections || []
      if (!dets.length) return `Кадр ${i + 1}: объекты не размечены`
      const m = new Map<string, number>()
      for (const d of dets) {
        const k = d.label_ru || equipmentRu(d.equipment_code)
        m.set(k, (m.get(k) || 0) + 1)
      }
      return `Кадр ${i + 1}: ${[...m.entries()].map(([k, n]) => `${k} ×${n}`).join(', ')}`
    })
    .join('; ')
}

function workLine(evidence: FindingEvidence | null): string {
  if (!evidence) return 'Работа не определена однозначно'
  if (evidence.match_status === 'ACCEPTED' && evidence.schedule_item?.name) {
    return evidence.schedule_item.name
  }
  return 'Не удалось однозначно связать наблюдение с работой'
}

function schemeStatusClass(s: DecisionSchemeNode['status']): string {
  if (s === 'passed') return 'is-passed'
  if (s === 'limited') return 'is-limited'
  return 'is-unknown'
}

export function FindingDrawer({
  open,
  onClose,
  title,
  subtitle,
  loading,
  evidence,
  decisionTrace,
  decisionTraceLoading,
  error,
  onRetry,
  variant = 'overlay',
  editorial,
  commentsSlot,
  onAcknowledge,
  acknowledgeBusy,
  onVerdict,
  verdictBusy,
  onReopen,
  reopenBusy,
  onVlmAssist,
  vlmBusy,
  vlmText,
  projectId,
  onExport,
  exportBusy,
  workCandidates,
  confirmedWorkId,
  onConfirmWorkLink,
  onRejectWorkLink,
  onConfirmSignal,
}: Props) {
  const [tab, setTab] = useState<'overview' | 'logic' | 'comment'>('overview')
  const [localDecisions, setLocalDecisions] = useState<SpecialistDecision[]>([])
  const [obsConfirmed, setObsConfirmed] = useState(false)
  const [scheduleImpact, setScheduleImpact] = useState<{
    status?: string
    message_ru?: string
    project_finish_delta_days?: number | null
    affected_successors?: number | null
    delay_days?: number | null
    absorbed_by_float?: boolean
    summary_lines?: string[]
  } | null>(null)
  /** Локальный what-if после confirm — не затирать API-эффектом. */
  const localImpactLockRef = useRef(false)
  const impactPanelRef = useRef<HTMLDivElement | null>(null)
  const [frameIndex, setFrameIndex] = useState(0)
  const [viewMode, setViewMode] = useState<'original' | 'annotated'>('annotated')
  const [selectedDet, setSelectedDet] = useState<number | null>(null)
  const [zoneSelected, setZoneSelected] = useState(false)
  const [layers, setLayers] = useState<LayerMode>('all')
  const [zoomOpen, setZoomOpen] = useState(false)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [schemeOpenId, setSchemeOpenId] = useState<string | null>(null)
  const [expertOpen, setExpertOpen] = useState(false)
  const [correctOpen, setCorrectOpen] = useState(false)
  const [correctWorkType, setCorrectWorkType] = useState('')
  const [correctScheduleId, setCorrectScheduleId] = useState('')

  const frames = evidence?.frames || []
  const kind = evidence?.signal_kind || (editorial ? 'RISK_FROM_SCHEDULE' : undefined)
  const isDemoStatic = kind === 'DEMO_STATIC_FINDING' || evidence?.demo_meta?.data_origin === 'DEMO_STATIC'
  const isCv = kind === 'CV_VERIFIED_FINDING' || kind === 'SYNTHETIC_DEMO_FINDING' || isDemoStatic
  const tone = kind === 'SYNTHETIC_DEMO_FINDING' || isDemoStatic ? 'risk' : isCv ? 'deviation' : 'risk'
  const activeFrame = frames[frameIndex]
  const hasAnnotated = Boolean(activeFrame?.overlay_url || (activeFrame?.detections?.length || 0) > 0 || activeFrame?.control_zone)
  const frameSrc =
    viewMode === 'annotated' && activeFrame?.overlay_url ? activeFrame.overlay_url : activeFrame?.image_url
  const showSvgOverlay =
    viewMode === 'annotated' &&
    !activeFrame?.overlay_url &&
    ((activeFrame?.detections?.length || 0) > 0 || Boolean(activeFrame?.control_zone))

  // Прогрев кадров при открытии карточки — меньше гонки «разметка раньше фото»
  useEffect(() => {
    const list = evidence?.frames || []
    preloadEvidenceImages(list.map((f) => f.image_url || f.overlay_url))
  }, [evidence?.frames])

  const frameAspect =
    activeFrame?.natural_width && activeFrame?.natural_height
      ? `${activeFrame.natural_width} / ${activeFrame.natural_height}`
      : undefined

  const headTitle = isDemoStatic ? evidence?.demo_meta?.title || 'Проверить комплект техники' : title
  const headStatus = (() => {
    if (isDemoStatic) return 'Предупреждение'
    if (obsConfirmed || localDecisions.some((d) => /подтверд/i.test(d.action))) return 'Подтверждено'
    return lifecycleRu(evidence?.lifecycle || undefined) || signalRu(kind)
  })()
  const headSubtitle = isDemoStatic ? stroginoDemoSubtitle() : subtitle

  const briefText = isDemoStatic
    ? evidence?.demo_meta?.brief || evidence?.explanation_ru || '—'
    : evidence?.explanation_ru || evidence?.card?.why || editorial?.text || '—'

  const signalBasis = isDemoStatic
    ? evidence?.demo_meta?.rule_result_ru || evidence?.demo_meta?.rule_name || 'Условие правила требует проверки'
    : evidence?.card?.check || editorial?.rule || 'Условие правила требует проверки'

  const checkAction =
    evidence?.card?.check ||
    'Подтвердите наблюдение, связь с работой и решение по сигналу.'

  const scenarioId = useMemo(() => {
    const fromFinding = evidence?.finding_id ? scenarioIdFromUiDeviationId(evidence.finding_id) : null
    if (fromFinding) return fromFinding
    return scenarioIdFromUiDeviationId(evidence?.deviation_id)
  }, [evidence?.finding_id, evidence?.deviation_id])

  const schemeNodes: DecisionSchemeNode[] = useMemo(() => {
    if (scenarioId) return buildScenarioDecisionScheme(scenarioId)
    if (isDemoStatic) return buildScenarioDecisionScheme('equipment-composition')
    return schemeFromDecisionTrace(decisionTrace)
  }, [isDemoStatic, decisionTrace, scenarioId])

  useEffect(() => {
    setFrameIndex(0)
    setViewMode('annotated')
    setSelectedDet(null)
    setZoneSelected(false)
    setLayers('all')
    setZoomOpen(false)
    setDetailsOpen(false)
    setSchemeOpenId(null)
    setExpertOpen(false)
    setCorrectOpen(false)
    setCorrectWorkType('')
    setCorrectScheduleId(evidence?.schedule_item?.id ? String(evidence.schedule_item.id) : '')
    if (scenarioId) setLocalDecisions(loadSpecialistDecisions(scenarioId))
    else setLocalDecisions([])
    // Восстановить сессионный what-if (если пользователь уже подтверждал в этой вкладке)
    const sessionRev = projectId ? loadSessionScheduleRevision(projectId) : null
    const workId = evidence?.schedule_item?.id ? String(evidence.schedule_item.id) : null
    const decisions = scenarioId ? loadSpecialistDecisions(scenarioId) : []
    const confirmedHere =
      decisions.some((d) => /подтвержд/i.test(d.action)) ||
      Boolean(sessionRev && workId && (sessionRev.driverActivityId === workId || sessionRev.revisedActivityIds.includes(workId)))
    if (sessionRev && confirmedHere) {
      // График уже пересчитан в сессии, но блок в карточке показываем только после нового «Подтвердить»
      localImpactLockRef.current = true
      setScheduleImpact(null)
      setObsConfirmed(false)
    } else {
      localImpactLockRef.current = false
      setScheduleImpact(null)
      setObsConfirmed(false)
    }
    const tourActive = Boolean(document.querySelector('[data-tour-id="tour-coach"]'))
    if (!tourActive) setTab('overview')
  }, [evidence?.deviation_id, evidence?.finding_id, scenarioId, projectId, evidence?.schedule_item?.id])

  useEffect(() => {
    setSelectedDet(null)
    setZoneSelected(false)
    if (viewMode === 'annotated' && !hasAnnotated) setViewMode('original')
  }, [frameIndex, hasAnnotated, viewMode])

  useEffect(() => {
    // Локальный пересмотр после confirm важнее фонового API-сценария
    if (localImpactLockRef.current || isDemoStatic) return
    const life = (evidence?.lifecycle || '').toUpperCase()
    const sid = evidence?.schedule_item?.id
    const codesOk = ['SCHEDULE_LAG', 'POSSIBLE_LATE_START', 'WORK_AFTER_PLAN'].includes(String(evidence?.code || ''))
    if (!projectId || !sid || !codesOk || !['CONFIRMED', 'VERIFIED', 'RESOLVED'].includes(life)) {
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const res = await fetch(`/api/projects/${projectId}/scenarios`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            template: 'DELAY_ACTIVITY',
            activity_id: String(sid),
            extra_days: 3,
            confirmed_finding_ids: [evidence?.deviation_id || evidence?.finding_id].filter(Boolean),
          }),
        })
        const data = await res.json()
        if (!cancelled && !localImpactLockRef.current) {
          setScheduleImpact({
            status: data.status,
            message_ru: data.message_ru || data.note,
            project_finish_delta_days: data.project_finish_delta_days ?? data.impact?.project_finish_delta_days,
            affected_successors: data.affected_successors ?? data.impact?.affected_successors,
            delay_days: data.delay_days ?? data.impact?.extra_days ?? 3,
            absorbed_by_float: data.absorbed_by_float ?? data.impact?.absorbed_by_float,
          })
        }
      } catch {
        if (!cancelled && !localImpactLockRef.current) {
          setScheduleImpact({ status: 'FORECAST_UNAVAILABLE', message_ru: 'Пересчёт сроков недоступен' })
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [projectId, evidence?.lifecycle, evidence?.schedule_item?.id, evidence?.code, evidence?.deviation_id, evidence?.finding_id, isDemoStatic])

  const showLocalImpact = (rev: ScheduleRevisionResult) => {
    localImpactLockRef.current = true
    setObsConfirmed(true)
    setScheduleImpact({
      status: rev.status,
      message_ru: rev.messageRu,
      project_finish_delta_days: rev.projectFinishDeltaDays,
      affected_successors: rev.affectedSuccessors,
      delay_days: rev.impactDays,
      absorbed_by_float: rev.absorbedByFloatDays > 0,
      summary_lines: rev.summaryLines,
    })
    window.requestAnimationFrame(() => {
      impactPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    })
  }

  const applyConfirmSignal = () => {
    if (!scenarioId && !onConfirmSignal && !onVerdict) return
    const w = workCandidates?.[0]
    const workId = confirmedWorkId || w?.id || evidence?.schedule_item?.id || null
    const workName = w?.name || evidence?.schedule_item?.name || null
    if (scenarioId) {
      if (w) onConfirmWorkLink?.(w.id, w.name)
      setLocalDecisions(
        saveSpecialistDecision(scenarioId, {
          level: 'signal',
          action: 'Сигнал подтверждён',
          at: new Date().toISOString(),
          workId: workId || undefined,
          workName: workName || undefined,
        }),
      )
    }
    // Сначала быстрый локальный what-if — не ждём backend verdict
    const rev = onConfirmSignal?.({ scenarioId, workId: workId ? String(workId) : null, workName })
    if (rev) {
      showLocalImpact(rev)
      return
    }
    if (scenarioId) {
      const f = getScenarioForecastImpact(scenarioId)
      if (f.status === 'calculated') {
        localImpactLockRef.current = true
        setObsConfirmed(true)
        setScheduleImpact({
          status: 'revised',
          message_ru: 'График пересмотрен с учётом критического пути.',
          project_finish_delta_days: 0,
          delay_days: f.impactDays,
          absorbed_by_float: false,
          summary_lines: [
            f.impactDays > 0
              ? `Дата завершения работы смещается на +${f.impactDays} дн.`
              : 'Срок завершения этой работы по прогнозу не меняется',
            'Основное строительство в датах не изменяется — запас сети удерживает финиш проекта',
          ],
        })
        window.requestAnimationFrame(() => {
          impactPanelRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
        })
      }
    }
  }

  useEffect(() => {
    if (!open) return
    return registerTourBridge({
      finding: {
        setTab: (t) => {
          if (t === 'proofs') {
            setTab('overview')
            setViewMode('annotated')
            setLayers('all')
            setZoomOpen(true)
            return
          }
          if (t === 'logic' || t === 'comment' || t === 'overview') {
            setZoomOpen(false)
            setTab(t)
          }
        },
        setFrameIndex: (index) => setFrameIndex(Math.max(0, index)),
        setViewMode: (mode) => setViewMode(mode),
        openZoom: (index) => {
          if (index != null) setFrameIndex(Math.max(0, index))
          setViewMode('annotated')
          setLayers('all')
          setZoomOpen(true)
        },
        closeZoom: () => setZoomOpen(false),
        confirmSignal: () => {
          // Всегда локальный пересмотр; backend verdict — параллельно, без блокировки UI
          applyConfirmSignal()
          if (!isDemoStatic && !scenarioId) onVerdict?.('confirm')
        },
      },
    })
  }, [open, isDemoStatic, scenarioId, confirmedWorkId, workCandidates, evidence?.schedule_item?.id, onConfirmSignal, onConfirmWorkLink, onVerdict])

  if (!open) return null

  const openViewer = (idx?: number) => {
    if (idx != null) setFrameIndex(idx)
    setZoomOpen(true)
  }

  const renderFrameStage = (opts: { compact?: boolean; interactive?: boolean }) => {
    const aspect = frameAspect
    return (
      <div
        className={`evidence-viewer-frame${aspect ? ' has-aspect' : ''}${opts.compact ? ' is-compact' : ''}`}
        style={{
          background: '#dfe6ee',
          position: 'relative',
          ...(aspect ? { aspectRatio: aspect, height: 'auto' } : null),
        }}
        data-tour-id="finding-evidence-frame"
      >
        {frameSrc ? (
          <EvidenceFrameView
            imgKey={`${activeFrame?.id}-${viewMode}-${frameSrc}`}
            src={frameSrc}
            showOverlay={showSvgOverlay}
            detections={activeFrame?.detections}
            zone={activeFrame?.control_zone || null}
            naturalWidth={activeFrame?.natural_width || 1000}
            naturalHeight={activeFrame?.natural_height || 1000}
            selectedDet={selectedDet}
            onSelectDet={opts.interactive ? setSelectedDet : undefined}
            showLabels={!opts.compact}
            showConfidence
            layers={layers}
            zoneSelected={zoneSelected}
            onSelectZone={
              opts.interactive
                ? () => {
                    setZoneSelected(true)
                    setSelectedDet(null)
                  }
                : undefined
            }
            tourId="finding-evidence-detections"
            onImgError={(e) => {
              const el = e.currentTarget
              el.style.display = 'none'
              const parent = el.parentElement
              if (parent && !parent.querySelector('.img-fallback')) {
                const p = document.createElement('p')
                p.className = 'img-fallback'
                p.style.cssText = 'padding:24px;color:#667;margin:0'
                p.textContent = 'Кадр недоступен'
                parent.appendChild(p)
              }
            }}
          />
        ) : (
          <p className="img-fallback" style={{ padding: 24, color: '#667', margin: 0 }}>
            Кадр недоступен
          </p>
        )}
        {!isDemoStatic && activeFrame?.captured_at && (
          <span className="evidence-viewer-time" data-tour-id="finding-evidence-timestamp">
            {fmtRuDateTime(activeFrame.captured_at)}
            <i />
          </span>
        )}
        {isDemoStatic && (activeFrame?.scenario_time_label || activeFrame?.source_visible_date) && (
          <span className="evidence-viewer-time" data-tour-id="finding-evidence-timestamp">
            {activeFrame.scenario_time_label || `Отметка периода: ${activeFrame.source_visible_date}`}
          </span>
        )}
      </div>
    )
  }

  const panel = (
    <aside
      className={`evidence-panel tone-${tone}${variant === 'inline' ? ' is-inline' : ''}${isDemoStatic ? ' is-reworked' : ''}${zoomOpen ? ' is-dimmed-by-zoom' : ''}`}
      role="dialog"
      aria-modal={variant === 'overlay' ? 'false' : undefined}
      aria-label={headTitle}
      data-tour-id="finding-card"
    >
      <div className="evidence-panel-head">
        <i className={`gantt-evidence evidence-${tone} is-static`} aria-hidden />
        <div className="evidence-panel-title">
          <small>{headStatus}</small>
          <b>{headTitle}</b>
          <span>{headSubtitle}</span>
        </div>
        <button type="button" className="evidence-close" onClick={(e) => { e.preventDefault(); e.stopPropagation(); onClose() }} aria-label="Закрыть">
          ×
        </button>
      </div>

      <div className="evidence-tabs">
        <button type="button" className={tab === 'overview' ? 'active' : ''} onClick={() => setTab('overview')}>
          Обзор
        </button>
        {schemeNodes.length > 0 && (
          <button
            type="button"
            className={tab === 'logic' ? 'active' : ''}
            onClick={() => setTab('logic')}
            data-tour-id="finding-logic-tab"
          >
            Логика
          </button>
        )}
        <button type="button" className={tab === 'comment' ? 'active' : ''} onClick={() => setTab('comment')}>
          Комментарии
        </button>
      </div>

      <div className="evidence-panel-body">
        {loading && <div className="panel" style={{ padding: 16 }}>Загрузка доказательств…</div>}
        {!loading && error && (
          <div className="panel evidence-error" style={{ padding: 16 }} data-tour-id="finding-error">
            <b>Не удалось загрузить доказательства</b>
            <p style={{ color: 'var(--muted)', margin: '8px 0' }}>{error}</p>
            {onRetry && (
              <button type="button" className="header-action" onClick={onRetry}>
                Повторить
              </button>
            )}
          </div>
        )}

        {!loading && !error && tab === 'overview' && (
          <div className="finding-overview-rework">
            {/* A. Краткий вывод */}
            <section className="finding-brief" data-tour-id="finding-brief">
              <b>
                {isDemoStatic
                  ? evidence?.demo_meta?.brief || headTitle
                  : editorial?.title || deviationCodeRu(evidence?.code) || headTitle}
              </b>
              <p>{isDemoStatic ? evidence?.explanation_ru || briefText : briefText}</p>
            </section>

            {/* B. Доказательства сразу */}
            {frames.length > 0 ? (
              <section className="finding-proof-grid" data-tour-id="finding-evidence-tab" aria-label="Кадры-доказательства">
                {frames.map((fr, i) => {
                  const aspect =
                    fr.natural_width && fr.natural_height ? `${fr.natural_width} / ${fr.natural_height}` : undefined
                  const hasOverlay = Boolean(fr.detections?.length || fr.control_zone)
                  return (
                    <button
                      type="button"
                      key={fr.frame_key || fr.id || i}
                      className={`finding-proof-card${frameIndex === i ? ' is-active' : ''}`}
                      onClick={() => openViewer(i)}
                      data-tour-id={i === 0 ? 'finding-evidence-thumb' : undefined}
                    >
                      <div className="finding-proof-thumb" style={aspect ? { aspectRatio: aspect } : undefined}>
                        {fr.image_url ? (
                          <EvidenceFrameView
                            src={fr.image_url}
                            showOverlay={hasOverlay}
                            detections={fr.detections}
                            zone={fr.control_zone || null}
                            naturalWidth={fr.natural_width || 1000}
                            naturalHeight={fr.natural_height || 1000}
                            selectedDet={null}
                            showLabels={false}
                            showConfidence={false}
                            layers="all"
                          />
                        ) : (
                          <span className="img-fallback">Кадр недоступен</span>
                        )}
                      </div>
                      <div className="finding-proof-meta">
                        <b>Кадр {i + 1}</b>
                        <span>
                          {fr.scenario_time_label ||
                            (fr.source_visible_date
                              ? `Отметка периода: ${fr.source_visible_date}`
                              : fr.captured_at
                                ? fmtRuDate(fr.captured_at)
                                : 'Отметка периода не указана')}
                        </span>
                        <em>Открыть кадр</em>
                      </div>
                    </button>
                  )
                })}
              </section>
            ) : (
              !isCv && (
                <p className="finding-no-frames">Для риска по графику кадры не применяются.</p>
              )
            )}

            {/* C. Сводка основания */}
            {isDemoStatic ? (
              <table className="finding-compare" aria-label="Почему сигнал">
                <tbody>
                  <tr>
                    <th>Работа КСГ</th>
                    <td>
                      {confirmedWorkId
                        ? workCandidates?.find((w) => w.id === confirmedWorkId)?.name
                        : workCandidates?.[0]?.name || evidence?.demo_meta?.work_label || '—'}
                      {evidence?.demo_meta?.work_wbs && (
                        <small style={{ display: 'block', color: '#6a829a', marginTop: 2 }}>
                          Код {evidence.demo_meta.work_wbs}
                          {evidence.demo_meta.plan_window ? ` · план: ${evidence.demo_meta.plan_window}` : ''}
                        </small>
                      )}
                      <small style={{ display: 'block', color: '#6a829a', marginTop: 2 }}>
                        Связь с КСГ: {evidence?.demo_meta?.task_link_status || 'Предполагаемая'}
                      </small>
                    </td>
                  </tr>
                  <tr>
                    <th>Ожидается</th>
                    <td>{evidence?.demo_meta?.expected || '—'}</td>
                  </tr>
                  <tr>
                    <th>На кадрах</th>
                    <td>{evidence?.demo_meta?.observed_hint || observationLine(frames)}</td>
                  </tr>
                  <tr>
                    <th>Основание</th>
                    <td>{evidence?.demo_meta?.rule_result_ru || signalBasis}</td>
                  </tr>
                  {evidence?.demo_meta?.observation_stamp && (
                    <tr>
                      <th>Отметка на кадрах</th>
                      <td>
                        {evidence.demo_meta.observation_stamp}
                        <small style={{ display: 'block', color: '#6a829a', marginTop: 4 }}>
                          Не метка камеры; не подтверждает автоматически период работ по КСГ
                        </small>
                      </td>
                    </tr>
                  )}
                  {evidence?.demo_meta?.plan_window && (
                    <tr>
                      <th>Период работы по КСГ</th>
                      <td>{evidence.demo_meta.plan_window}</td>
                    </tr>
                  )}
                  {evidence?.demo_meta?.delay_note && (
                    <tr>
                      <th>Прогноз по срокам</th>
                      <td>{evidence.demo_meta.delay_note}</td>
                    </tr>
                  )}
                  {evidence?.demo_meta?.normative_formulation && (
                    <tr>
                      <th>Что проверить по документам</th>
                      <td>
                        {evidence.demo_meta.normative_formulation}
                        {evidence.demo_meta.normative_refs?.length ? (
                          <small style={{ display: 'block', color: '#6a829a', marginTop: 4 }}>
                            Ориентиры: {evidence.demo_meta.normative_refs.join('; ')}
                          </small>
                        ) : null}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            ) : (
              <dl className="finding-interp">
                <div>
                  <dt>Наблюдение</dt>
                  <dd>{isCv ? observationLine(frames) : editorial?.detected || '—'}</dd>
                </div>
                <div>
                  <dt>Основание</dt>
                  <dd>{signalBasis}</dd>
                </div>
              </dl>
            )}

            {/* D. Решение */}
            <section className="finding-next">
              <b>Ваше решение</b>
              <div className="finding-next-actions">
                {(isDemoStatic || scenarioId) && (
                  <>
                    <button
                      type="button"
                      className="primary finish-edit"
                      data-tour-id="finding-confirm"
                      onClick={() => applyConfirmSignal()}
                    >
                      Подтвердить
                    </button>
                    <button
                      type="button"
                      className="header-action"
                      data-tour-id="finding-reject"
                      onClick={() => {
                        if (!scenarioId) return
                        onRejectWorkLink?.()
                        setLocalDecisions(
                          saveSpecialistDecision(scenarioId, {
                            level: 'signal',
                            action: 'Сигнал отклонён',
                            at: new Date().toISOString(),
                          }),
                        )
                      }}
                    >
                      Отклонить
                    </button>
                    <button
                      type="button"
                      className="header-action"
                      onClick={() => {
                        if (!scenarioId) return
                        setLocalDecisions(
                          saveSpecialistDecision(scenarioId, {
                            level: 'signal',
                            action: 'Недостаточно данных',
                            at: new Date().toISOString(),
                          }),
                        )
                      }}
                    >
                      Мало данных
                    </button>
                  </>
                )}
                {!isDemoStatic && onVerdict && (
                  <>
                    <button
                      type="button"
                      className="primary finish-edit"
                      data-tour-id="finding-confirm"
                      disabled={evidence?.lifecycle === 'RESOLVED'}
                      onClick={() => {
                        // Локальный пересмотр сразу; API — в фоне (не блокируем карточку)
                        applyConfirmSignal()
                        onVerdict('confirm')
                      }}
                    >
                      Подтвердить
                    </button>
                    <button
                      type="button"
                      className="header-action"
                      data-tour-id="finding-reject"
                      disabled={verdictBusy || evidence?.lifecycle === 'RESOLVED'}
                      onClick={() => onVerdict('reject')}
                    >
                      Отклонить
                    </button>
                    <button
                      type="button"
                      className="header-action"
                      disabled={verdictBusy || evidence?.lifecycle === 'RESOLVED'}
                      onClick={() => onAcknowledge?.() || onVerdict('correct', { reason: 'insufficient_data' })}
                    >
                      Мало данных
                    </button>
                  </>
                )}
              </div>
              {localDecisions.length > 0 && (
                <p className="finding-next-note">Зафиксировано: {localDecisions[localDecisions.length - 1]?.action}</p>
              )}
            </section>

            {/* E. Контекст */}
            <details
              className="finding-details"
              open={detailsOpen}
              onToggle={(e) => setDetailsOpen((e.target as HTMLDetailsElement).open)}
            >
              <summary>Контекст и ограничения</summary>
              <ul>
                {evidence?.demo_meta?.zone_label && <li>Зона наблюдения: {evidence.demo_meta.zone_label}</li>}
                {evidence?.demo_meta?.observation_stamp && (
                  <li>Отметка на изображении: {evidence.demo_meta.observation_stamp} (не метка камеры)</li>
                )}
                {isDemoStatic && !evidence?.demo_meta?.observation_stamp && (
                  <li>Отметка периода на кадрах не указана — наблюдаемость во времени ограничена</li>
                )}
                {evidence?.demo_meta?.plan_window && <li>Период работы по КСГ: {evidence.demo_meta.plan_window}</li>}
                {evidence?.demo_meta?.task_link_status && (
                  <li>Статус связи с КСГ: {evidence.demo_meta.task_link_status}</li>
                )}
                {evidence?.demo_meta?.evidence_status && (
                  <li>Достаточность доказательств: {evidence.demo_meta.evidence_status}</li>
                )}
                {frames.length > 0 && <li>Кадров в разборе: {frames.filter((f) => f.image_url).length}</li>}
                {evidence?.demo_meta?.delay_note && <li>{evidence.demo_meta.delay_note}</li>}
                {evidence?.demo_meta?.normative_observation && (
                  <li>{evidence.demo_meta.normative_observation}</li>
                )}
                {isDemoStatic &&
                  (evidence?.limitations || []).map((l, i) => (
                    <li key={`lim-${i}`}>{l}</li>
                  ))}
                {!isDemoStatic && evidence?.schedule_item?.planned_finish && (
                  <li>План. окончание: {fmtRuDate(evidence.schedule_item.planned_finish)}</li>
                )}
                {!isDemoStatic &&
                  limitationsRu(evidence?.limitations).map((l, i) => (
                    <li key={i}>{l}</li>
                  ))}
              </ul>
            </details>

            {!isDemoStatic && projectId && evidence?.schedule_item?.id && (
              <WorkCompletePanel
                projectId={projectId}
                scheduleItemId={evidence.schedule_item.id}
                lifecycle={evidence.lifecycle}
              />
            )}

            {!isDemoStatic && !isCv && editorial && (
              <div className="evidence-facts" style={{ marginTop: 12 }}>
                <div>
                  <span>Актуальная дата</span>
                  <b>{editorial.asOf || asOfCaption()}</b>
                </div>
                {editorial.state && (
                  <div>
                    <span>Статус работы</span>
                    <b>{activityStateRu(editorial.state)}</b>
                  </div>
                )}
                <div>
                  <span>План / факт</span>
                  <b>
                    {Math.round(evidence?.schedule_item?.planned_progress ?? editorial.plan ?? 0)}% /{' '}
                    {Math.round(evidence?.schedule_item?.actual_progress ?? editorial.fact ?? 0)}%
                  </b>
                </div>
              </div>
            )}

            {scheduleImpact && obsConfirmed && (
              <div
                ref={impactPanelRef}
                className={`evidence-subpanel schedule-impact-panel${scheduleImpact.status === 'absorbed' ? ' is-absorbed' : ' is-revised'}`}
                data-tour-id="schedule-impact"
              >
                <b className="evidence-subpanel-title">Пересмотр графика</b>
                <p className="evidence-subpanel-text">
                  {scheduleImpact.message_ru || 'График пересмотрен с учётом критического пути.'}
                </p>
                {(scheduleImpact.summary_lines?.length ||
                  scheduleImpact.delay_days != null ||
                  scheduleImpact.project_finish_delta_days != null) && (
                  <ul className="evidence-subpanel-list" data-tour-id="schedule-impact-details">
                    {scheduleImpact.summary_lines?.map((line, i) => (
                      <li key={i}>{line}</li>
                    ))}
                    {!scheduleImpact.summary_lines?.length && scheduleImpact.delay_days != null && (
                      <li>Дата завершения работы смещается на +{scheduleImpact.delay_days} дн.</li>
                    )}
                    {!scheduleImpact.summary_lines?.length &&
                      (scheduleImpact.project_finish_delta_days == null ||
                        scheduleImpact.project_finish_delta_days === 0) && (
                        <li>Основное строительство в датах не изменяется</li>
                      )}
                    {!scheduleImpact.summary_lines?.length &&
                      scheduleImpact.project_finish_delta_days != null &&
                      scheduleImpact.project_finish_delta_days > 0 && (
                        <li>Прогнозный финиш проекта: +{scheduleImpact.project_finish_delta_days} дн.</li>
                      )}
                  </ul>
                )}
                <div className="evidence-subpanel-actions">
                  <button type="button" className="header-action" onClick={onClose} data-tour-id="schedule-impact-close">
                    Закрыть и смотреть график
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {!loading && !error && tab === 'logic' && (
          <div data-tour-id="finding-logic-panel" className="finding-scheme-wrap">
            <p className="finding-logic-lead">
              Как система пришла к сигналу: от кадров наблюдения к работе КСГ и решению о сроках. Каждый шаг можно проверить.
            </p>
            {decisionTraceLoading && <p style={{ color: 'var(--muted)' }}>Загрузка схемы…</p>}
            {!decisionTraceLoading && schemeNodes.length === 0 && (
              <p style={{ color: 'var(--muted)' }}>Цепочка решения недоступна для этого предупреждения.</p>
            )}
            <ol className="finding-scheme" aria-label="Схема принятия решения">
              {schemeNodes.map((node, idx) => (
                <li key={node.id} className={schemeStatusClass(node.status)} data-tour-id={TRACE_TOUR_ID[node.id] || `finding-trace-${node.id}`}>
                  {idx > 0 && <span className="finding-scheme-arrow" aria-hidden />}
                  <button
                    type="button"
                    className={`finding-scheme-node${schemeOpenId === node.id ? ' is-open' : ''}`}
                    onClick={() => setSchemeOpenId((cur) => (cur === node.id ? null : node.id))}
                  >
                    <span className="finding-scheme-title">{node.title}</span>
                    <span className="finding-scheme-result">{node.result}</span>
                    <span className={`finding-scheme-status status-${node.status}`}>
                      {node.status === 'passed'
                        ? 'Пройден'
                        : node.status === 'limited'
                          ? 'Ограничение'
                          : 'Недостаточно данных'}
                    </span>
                  </button>
                  {schemeOpenId === node.id && node.detail && (
                    <p className="finding-scheme-detail">{node.detail}</p>
                  )}
                </li>
              ))}
            </ol>
            {onVlmAssist && !isDemoStatic && (
              <div className="panel" style={{ padding: 12, marginTop: 12 }}>
                <button type="button" className="admin-btn" disabled={vlmBusy} onClick={onVlmAssist} data-tour-id="vlm-assist">
                  {vlmBusy ? 'Готовим пояснение…' : 'Пояснить по кадрам'}
                </button>
                {vlmText && <p style={{ marginTop: 10, fontSize: 13, lineHeight: 1.45 }}>{vlmText}</p>}
              </div>
            )}
            {decisionTrace && !isDemoStatic && (
              <div className="panel" style={{ padding: 12, marginTop: 12 }}>
                <button type="button" className="admin-btn" onClick={() => setExpertOpen((v) => !v)}>
                  {expertOpen ? 'Скрыть технические детали' : 'Показать технические детали'}
                </button>
                {expertOpen && (
                  <div style={{ marginTop: 10, fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }}>
                    <div>Тип предупреждения: {deviationCodeRu(decisionTrace.rule?.code || evidence?.code)}</div>
                    <div>Источник разбора: сохранённая цепочка решения</div>
                    <div>
                      Оценка активности:{' '}
                      {decisionTrace.activity?.engine === 'heuristic_v2' ? 'эвристика' : 'служебный модуль'}
                    </div>
                    <div>Модель детекции: {(decisionTrace.cv?.model as { name?: string } | null | undefined)?.name || '—'}</div>
                    <div>Повторный анализ кадров не выполняется</div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {!loading && !error && tab === 'comment' && (commentsSlot || <div className="panel" style={{ padding: 16 }}>Комментарии недоступны</div>)}
      </div>

      <div className="evidence-panel-foot">
        <div className="evidence-actions">
          {onExport && (
            <button
              type="button"
              className="header-action"
              data-tour-id="finding-export-docx"
              disabled={exportBusy}
              onClick={() => onExport()}
              title="Сформировать отчёт Word по предупреждению"
            >
              {exportBusy ? '…' : 'Сформировать отчёт'}
            </button>
          )}
          {onAcknowledge && !isDemoStatic && (
            <button
              type="button"
              className="header-action"
              data-tour-id="finding-ack"
              disabled={acknowledgeBusy || evidence?.lifecycle === 'ACKNOWLEDGED' || evidence?.lifecycle === 'RESOLVED'}
              onClick={onAcknowledge}
            >
              {evidence?.lifecycle === 'ACKNOWLEDGED' ? 'В проверке' : 'Принять к проверке'}
            </button>
          )}
          {onReopen && (
            <button type="button" className="header-action" disabled={reopenBusy} onClick={onReopen}>
              Вернуть в работу
            </button>
          )}
          {onVerdict && !isDemoStatic && (
            <button type="button" className="header-action" data-tour-id="finding-correct" disabled={verdictBusy} onClick={() => setCorrectOpen((v) => !v)}>
              Исправить
            </button>
          )}
        </div>
        {correctOpen && onVerdict && (
          <div className="evidence-correct-form">
            <label>
              Вид работы (код / название)
              <input value={correctWorkType} onChange={(e) => setCorrectWorkType(e.target.value)} />
            </label>
            <label>
              Привязка к строке КСГ (id)
              <input value={correctScheduleId} onChange={(e) => setCorrectScheduleId(e.target.value)} />
            </label>
            <button
              type="button"
              className="primary finish-edit"
              disabled={verdictBusy || (!correctWorkType.trim() && !correctScheduleId.trim())}
              onClick={() => {
                const correction: Record<string, unknown> = {}
                if (correctWorkType.trim()) {
                  correction.ground_truth_work_type = correctWorkType.trim()
                  correction.work_type_code = correctWorkType.trim()
                }
                if (correctScheduleId.trim()) {
                  const n = Number(correctScheduleId.trim())
                  correction.schedule_item_id = Number.isFinite(n) ? n : correctScheduleId.trim()
                }
                onVerdict('correct', correction)
                setCorrectOpen(false)
              }}
            >
              Сохранить исправление
            </button>
          </div>
        )}
      </div>
    </aside>
  )

  const zoomModal =
    zoomOpen && frames.length > 0
      ? createPortal(
          <div
            className="evidence-zoom-overlay"
            role="dialog"
            aria-modal="true"
            aria-label="Просмотр кадра"
            data-tour-id="frame-zoom-modal"
            onClick={() => setZoomOpen(false)}
          >
            <div className="evidence-zoom-dialog evidence-zoom-dialog-wide evidence-zoom-dialog-light" onClick={(e) => e.stopPropagation()}>
              <div className="evidence-zoom-head">
                <div>
                  <b>
                    Кадр {frameIndex + 1}
                    {frames.length > 1 ? ` / ${frames.length}` : ''}
                    {activeFrame?.source_visible_date ? ` · ${activeFrame.source_visible_date}` : ''}
                  </b>
                  {!activeFrame?.source_visible_date && activeFrame?.scenario_time_label && (
                    <span className="evidence-zoom-meta">{activeFrame.scenario_time_label}</span>
                  )}
                </div>
                <button type="button" className="evidence-close" onClick={() => setZoomOpen(false)} aria-label="Закрыть">
                  ×
                </button>
              </div>

              <div className="evidence-zoom-toolbar">
                <div className="evidence-view-toggle" role="group" aria-label="Режим кадра">
                  <button type="button" className={viewMode === 'original' ? 'active' : ''} onClick={() => setViewMode('original')} data-tour-id="frame-original">
                    Оригинал
                  </button>
                  <button
                    type="button"
                    className={viewMode === 'annotated' ? 'active' : ''}
                    disabled={!hasAnnotated}
                    onClick={() => setViewMode('annotated')}
                    data-tour-id="frame-annotated"
                  >
                    Разметка
                  </button>
                </div>
                <div className="evidence-layer-toggle" role="group" aria-label="Слои">
                  <button type="button" className={layers === 'equipment' ? 'active' : ''} onClick={() => setLayers('equipment')} disabled={viewMode !== 'annotated'}>
                    Техника
                  </button>
                  <button type="button" className={layers === 'zone' ? 'active' : ''} onClick={() => setLayers('zone')} disabled={viewMode !== 'annotated' || !activeFrame?.control_zone}>
                    Область
                  </button>
                  <button type="button" className={layers === 'all' ? 'active' : ''} onClick={() => setLayers('all')} disabled={viewMode !== 'annotated'}>
                    Все слои
                  </button>
                </div>
                <div className="evidence-zoom-nav" role="group" aria-label="Кадры">
                  <button type="button" disabled={frameIndex <= 0} onClick={() => setFrameIndex((i) => Math.max(0, i - 1))} aria-label="Предыдущий кадр">
                    ←
                  </button>
                  <button
                    type="button"
                    disabled={frameIndex >= frames.length - 1}
                    onClick={() => setFrameIndex((i) => Math.min(frames.length - 1, i + 1))}
                    aria-label="Следующий кадр"
                  >
                    →
                  </button>
                </div>
              </div>

              <div className="evidence-zoom-body">
                <div className="evidence-zoom-stage" style={frameAspect ? { aspectRatio: frameAspect } : undefined}>
                  {renderFrameStage({ compact: false, interactive: true })}
                </div>
                <aside className="evidence-zoom-side">
                  <b>На кадре</b>
                  {(activeFrame?.detections?.length || 0) === 0 && !activeFrame?.control_zone ? (
                    <p className="finding-next-note">Нет размеченных объектов</p>
                  ) : (
                    <ul className="evidence-det-list evidence-det-list-stack">
                      {(activeFrame?.detections || []).map((d, i) => (
                        <li
                          key={d.id || i}
                          className={selectedDet === i ? 'is-selected' : ''}
                          role="button"
                          tabIndex={0}
                          style={{ borderColor: demoClassColor(d.color_key, d.equipment_code) }}
                          onClick={() => {
                            setSelectedDet((cur) => (cur === i ? null : i))
                            setZoneSelected(false)
                          }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              setSelectedDet((cur) => (cur === i ? null : i))
                              setZoneSelected(false)
                            }
                          }}
                        >
                          <em className="evidence-det-idx">{i + 1}</em>
                          <b>{d.label_ru || equipmentRu(d.equipment_code)}</b>
                          {isRealConfidence(d) && (
                            <span className="evidence-det-conf">{Math.round(Number(d.confidence) * 100)}%</span>
                          )}
                        </li>
                      ))}
                      {activeFrame?.control_zone && (
                        <li
                          className={`evidence-zone-row${zoneSelected ? ' is-selected' : ''}`}
                          role="button"
                          tabIndex={0}
                          onClick={() => {
                            setZoneSelected(true)
                            setSelectedDet(null)
                            setLayers((l) => (l === 'equipment' ? 'all' : l))
                          }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              setZoneSelected(true)
                              setSelectedDet(null)
                              setLayers((l) => (l === 'equipment' ? 'all' : l))
                            }
                          }}
                        >
                          <em className="evidence-det-idx is-zone">З</em>
                          <b>{activeFrame.control_zone.legend || 'Область анализа'}</b>
                        </li>
                      )}
                    </ul>
                  )}
                </aside>
              </div>
            </div>
          </div>,
          document.body,
        )
      : null

  if (variant === 'inline') {
    return (
      <>
        {panel}
        {zoomModal}
      </>
    )
  }
  return (
    <>
      {createPortal(panel, document.body)}
      {zoomModal}
    </>
  )
}
