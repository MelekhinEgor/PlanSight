import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { activityStateRu, asOfCaption, deviationCodeRu, fmtRuDate, fmtRuDateTime, lifecycleRu, limitationRu, limitationsRu, signalKindRu } from '../labels/ru'
import { WorkCompletePanel } from './WorkCompletePanel'


export type FindingEvidence = {
  finding_id?: string | null
  deviation_id?: number | null
  signal_kind?: string
  code?: string
  lifecycle?: string | null
  explanation_ru?: string
  limitations?: string[]
  frames?: {
    id: number
    image_url?: string
    overlay_url?: string | null
    captured_at?: string | null
    camera_id?: number | null
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
  /** overlay — поверх графика; inline — встроенная панель на странице предупреждений */
  variant?: 'overlay' | 'inline'
  /** Editorial fallback при пустом API (RISK) */
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
}

function signalRu(kind?: string) {
  return signalKindRu(kind)
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
}: Props) {
  const [tab, setTab] = useState<'overview' | 'proofs' | 'logic' | 'comment'>('overview')
  const [scheduleImpact, setScheduleImpact] = useState<{
    status?: string
    message_ru?: string
    project_finish_delta_days?: number | null
    affected_successors?: number | null
    delay_days?: number | null
    absorbed_by_float?: boolean
  } | null>(null)
  const [frameIndex, setFrameIndex] = useState(0)
  const [expertOpen, setExpertOpen] = useState(false)
  const [correctOpen, setCorrectOpen] = useState(false)
  const [correctWorkType, setCorrectWorkType] = useState('')
  const [correctScheduleId, setCorrectScheduleId] = useState('')
  const frames = evidence?.frames || []
  const kind = evidence?.signal_kind || (editorial ? 'RISK_FROM_SCHEDULE' : undefined)
  const isCv = kind === 'CV_VERIFIED_FINDING' || kind === 'SYNTHETIC_DEMO_FINDING'
  const tone = kind === 'SYNTHETIC_DEMO_FINDING' ? 'risk' : isCv ? 'deviation' : 'risk'

  useEffect(() => {
    setFrameIndex(0)
    setExpertOpen(false)
    setCorrectOpen(false)
    setCorrectWorkType('')
    setCorrectScheduleId(evidence?.schedule_item?.id ? String(evidence.schedule_item.id) : '')
    setTab('overview')
    setScheduleImpact(null)
  }, [evidence?.deviation_id, evidence?.finding_id])

  useEffect(() => {
    const life = (evidence?.lifecycle || '').toUpperCase()
    const sid = evidence?.schedule_item?.id
    const codesOk = ['SCHEDULE_LAG', 'POSSIBLE_LATE_START', 'WORK_AFTER_PLAN'].includes(String(evidence?.code || ''))
    if (!projectId || !sid || !codesOk || !['CONFIRMED', 'VERIFIED', 'RESOLVED'].includes(life)) {
      setScheduleImpact(null)
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
        if (!cancelled) {
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
        if (!cancelled) setScheduleImpact({ status: 'FORECAST_UNAVAILABLE', message_ru: 'Пересчёт сроков недоступен' })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [projectId, evidence?.lifecycle, evidence?.schedule_item?.id, evidence?.code, evidence?.deviation_id, evidence?.finding_id])

  const meta = useMemo(() => {
    if (evidence && (evidence.explanation_ru || evidence.card)) {
      return {
        title: deviationCodeRu(evidence.code) || signalRu(kind),
        text: evidence.explanation_ru || evidence.card?.why || '—',
        expected: isCv
          ? (evidence.card?.what_seen?.length ? `Наблюдалось: ${evidence.card.what_seen.join(', ')}` : 'Ожидаемая активность в зоне')
          : editorial?.expected || 'Сроки по плану графика',
        detected: isCv
          ? lifecycleRu(evidence.lifecycle || undefined)
          : editorial?.detected || 'Риск по полям графика',
        rule: isCv ? 'Только кадры, привязанные к этому предупреждению' : 'План / факт / прогноз календарного графика',
        asOf: asOfCaption(evidence.as_of || undefined),
      }
    }
    if (editorial) {
      return {
        title: editorial.title,
        text: editorial.text,
        expected: editorial.expected,
        detected: editorial.detected,
        rule: editorial.rule,
        asOf: editorial.asOf || asOfCaption(),
      }
    }
    return null
  }, [evidence, editorial, isCv, kind])

  const logicSteps = useMemo(() => {
    return (decisionTrace?.user_logic || []).map((step) => {
      if (step.id !== 'limits') return step
      const parts = String(step.body || '')
        .split(';')
        .map((x) => x.trim())
        .filter(Boolean)
      const cleaned = limitationsRu(parts)
      return { ...step, body: cleaned.join('; ') || step.body }
    })
  }, [decisionTrace])

  const logicAvailable = logicSteps.length > 0

  useEffect(() => {
    if (tab === 'logic' && !logicAvailable) setTab('overview')
  }, [tab, logicAvailable])

  if (!open) return null

  const panel = (
    <aside
      className={`evidence-panel tone-${tone}${variant === 'inline' ? ' is-inline' : ''}`}
      role="dialog"
      aria-modal={variant === 'overlay' ? 'false' : undefined}
      aria-label={title}
      data-tour-id="finding-card"
    >
      <div className="evidence-panel-head">
        <i className={`gantt-evidence evidence-${tone} is-static`} aria-hidden />
        <div className="evidence-panel-title">
          <small>{signalRu(kind)}</small>
          <b>{title}</b>
          <span>{subtitle}</span>
        </div>
        <button type="button" className="evidence-close" onClick={onClose} aria-label="Закрыть">
          ×
        </button>
      </div>
      <div className="evidence-tabs">
        <button type="button" className={tab === 'overview' ? 'active' : ''} onClick={() => setTab('overview')}>
          Обзор
        </button>
        <button type="button" className={tab === 'proofs' ? 'active' : ''} onClick={() => setTab('proofs')}>
          Кадры ({frames.filter((f) => f.image_url).length})
        </button>
        {logicAvailable && (
          <button type="button" className={tab === 'logic' ? 'active' : ''} onClick={() => setTab('logic')} data-tour-id="finding-logic-tab">
            Логика
          </button>
        )}
        <button type="button" className={tab === 'comment' ? 'active' : ''} onClick={() => setTab('comment')}>
          Комментарий
        </button>
      </div>
      <div className="evidence-panel-body">
        {loading && <div className="panel" style={{ padding: 16 }}>Загрузка доказательств…</div>}
        {!loading && tab === 'overview' && meta && (
          <>
            <ol className="finding-checklist" aria-label="Разбор предупреждения">
              <li><b>Что увидели</b><span>{isCv ? (evidence?.card?.what_seen?.join(', ') || meta.detected) : 'Поля графика (не камера)'}</span></li>
              <li><b>На какой работе</b><span>{evidence?.schedule_item?.name || title}</span></li>
              <li><b>Почему подозрение</b><span>{meta.text}</span></li>
              <li><b>Кадры</b><span>{isCv ? `${frames.length} шт.` : 'Не применяются'}</span></li>
              <li><b>Что не можем установить</b><span>{limitationRu(evidence?.card?.unknown || evidence?.limitations?.[0]) || 'Процент готовности по фото не выводится'}</span></li>
              <li><b>Что проверить</b><span>{evidence?.card?.check || editorial?.rule || meta.rule}</span></li>
              <li><b>Ответственный / срок</b><span>{(evidence?.card as {owner?: string}|undefined)?.owner || 'Назначить в комментарии'} · {meta.asOf}</span></li>
              <li><b>Статус</b><span>{lifecycleRu(evidence?.lifecycle || undefined) || (isCv ? 'Открыто' : 'Риск по графику')}</span></li>
            </ol>
            {scheduleImpact && (
              <div className="evidence-subpanel" data-tour-id="schedule-impact">
                <b className="evidence-subpanel-title">Влияние на график</b>
                {scheduleImpact.status === 'FORECAST_UNAVAILABLE' ? (
                  <p className="evidence-subpanel-text">
                    Пересчёт сроков недоступен. {scheduleImpact.message_ru || 'В графике недостаточно подтверждённых зависимостей.'}
                  </p>
                ) : (
                  <p className="evidence-subpanel-text">
                    Подтверждённое отклонение: +{scheduleImpact.delay_days ?? '—'} дн.
                    {scheduleImpact.status === 'PARTIAL_NETWORK_PREVIEW' || scheduleImpact.message_ru ? (
                      <>
                        {' '}
                        {scheduleImpact.message_ru
                          || 'Прогноз рассчитан по доступному связанному фрагменту сети. Полное влияние на срок проекта не определяется: график содержит неполную сеть зависимостей.'}
                      </>
                    ) : null}
                    {scheduleImpact.project_finish_delta_days != null && scheduleImpact.status !== 'PARTIAL_NETWORK_PREVIEW' && (
                      <> · Прогноз завершения проекта: {scheduleImpact.project_finish_delta_days >= 0 ? '+' : ''}{scheduleImpact.project_finish_delta_days} дн.</>
                    )}
                    {scheduleImpact.affected_successors != null && <> · Затронуто последующих работ: {scheduleImpact.affected_successors}</>}
                    {scheduleImpact.absorbed_by_float ? ' · Часть задержки поглощена резервом.' : ''}
                    {' '}Сценарий не публикует график — только preview.
                  </p>
                )}
              </div>
            )}
            {projectId && evidence?.schedule_item?.id && (
              <WorkCompletePanel
                projectId={projectId}
                scheduleItemId={evidence.schedule_item.id}
                lifecycle={evidence.lifecycle}
              />
            )}
            <div className={`evidence-alert tone-${tone}`}>
              <b>{meta.title}</b>
              <p>{meta.text}</p>
            </div>
            <div className="evidence-facts">
              <div>
                <span>Актуальная дата</span>
                <b>{meta.asOf}</b>
              </div>
              <div>
                <span>Тип сигнала</span>
                <b>{signalRu(kind)}</b>
              </div>
              {editorial?.state && (
                <div>
                  <span>Статус работы</span>
                  <b>{activityStateRu(editorial.state)}</b>
                </div>
              )}
              <div>
                <span>Ожидалось</span>
                <b>{meta.expected}</b>
              </div>
              <div>
                <span>Обнаружено</span>
                <b>{meta.detected}</b>
              </div>
              <div>
                <span>Как считали</span>
                <b>{meta.rule}</b>
              </div>
              <div>
                <span>План / факт</span>
                <b>
                  {Math.round(evidence?.schedule_item?.planned_progress ?? editorial?.plan ?? 0)}% /{' '}
                  {Math.round(evidence?.schedule_item?.actual_progress ?? editorial?.fact ?? 0)}%
                </b>
              </div>
              <div>
                <span>План. окончание</span>
                <b>{fmtRuDate(evidence?.schedule_item?.planned_finish || editorial?.plannedEnd || null)}</b>
              </div>
              <div>
                <span>Прогноз</span>
                <b>{fmtRuDate(evidence?.schedule_item?.forecast_end || editorial?.forecastEnd || null)}</b>
              </div>
            </div>
            {(limitationsRu(evidence?.limitations).length || 0) > 0 && (
              <div className="evidence-subpanel">
                <b className="evidence-subpanel-title">Ограничения</b>
                <ul className="evidence-subpanel-list">
                  {limitationsRu(evidence!.limitations).map((l, i) => (
                    <li key={i}>{l}</li>
                  ))}
                </ul>
              </div>
            )}
            {!isCv && (
              <p style={{ color: 'var(--muted)', fontSize: 12, marginTop: 12 }}>
                Для риска по графику кадры не показываются — это не наблюдение камеры.
              </p>
            )}
          </>
        )}
        {!loading && tab === 'proofs' && (
          <div className="evidence-proofs">
            {frames.length === 0 ? (
              <div className="panel" style={{ padding: 20 }}>
                <b>Нет кадров-доказательств</b>
                <p style={{ color: 'var(--muted)' }}>
                  {isCv
                    ? 'У предупреждения нет привязанных кадров — CV-вывод недоступен.'
                    : 'Риск по графику не использует кадры проекта.'}
                </p>
              </div>
            ) : (
              <>
                <div className="evidence-viewer">
                  <div className="evidence-viewer-frame" style={{ background: '#dfe6ee', position: 'relative' }}>
                    {frames[frameIndex]?.image_url ? (
                      <img
                        key={frames[frameIndex]?.id}
                        src={frames[frameIndex]?.image_url}
                        alt={`Кадр ${frames[frameIndex]?.id}`}
                        style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }}
                        onError={(e) => {
                          const el = e.currentTarget
                          el.style.display = 'none'
                          const parent = el.parentElement
                          if (parent && !parent.querySelector('.img-fallback')) {
                            const p = document.createElement('p')
                            p.className = 'img-fallback'
                            p.style.cssText = 'padding:24px;color:#667;margin:0'
                            p.textContent = 'Не удалось загрузить кадр. Перезапустите API и обновите страницу.'
                            parent.appendChild(p)
                          }
                        }}
                      />
                    ) : null}
                    <span className="evidence-viewer-time">
                      {fmtRuDateTime(frames[frameIndex]?.captured_at)}
                      <i />
                    </span>
                  </div>
                  <div className="evidence-pager" role="tablist" aria-label="Кадры">
                    {frames.map((_, i) => (
                      <button type="button" key={i} className={frameIndex === i ? 'active' : ''} onClick={() => setFrameIndex(i)}>
                        {i + 1}
                      </button>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        )}
        {!loading && tab === 'logic' && logicAvailable && (
          <div data-tour-id="finding-logic-panel">
            <ol className="finding-checklist" aria-label="Логика решения" style={{ whiteSpace: 'pre-line' }}>
              {logicSteps.map((step) => (
                <li key={step.id}>
                  <b>{step.title}</b>
                  <span>{step.body}</span>
                </li>
              ))}
            </ol>
            {onVlmAssist && (
              <div className="panel" style={{ padding: 12, marginTop: 12 }}>
                <button type="button" className="admin-btn" disabled={vlmBusy} onClick={onVlmAssist} data-tour-id="vlm-assist">
                  {vlmBusy ? 'Готовим пояснение…' : 'Пояснить по кадрам'}
                </button>
                {vlmText && <p style={{ marginTop: 10, fontSize: 13, lineHeight: 1.45 }}>{vlmText}</p>}
              </div>
            )}
            {decisionTrace && (
              <div className="panel" style={{ padding: 12, marginTop: 12 }}>
                <button type="button" className="admin-btn" onClick={() => setExpertOpen((v) => !v)}>
                  {expertOpen ? 'Скрыть технические детали' : 'Показать технические детали'}
                </button>
                {expertOpen && (
                  <div style={{ marginTop: 10, fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }}>
                    <div>Тип предупреждения: {deviationCodeRu(decisionTrace.rule?.code || evidence?.code)}</div>
                    <div>Источник разбора: сохранённая цепочка решения</div>
                    <div>
                      Оценка активности: {decisionTrace.activity?.engine === 'heuristic_v2' ? 'эвристика' : 'служебный модуль'}
                    </div>
                    <div>Модель детекции: {(decisionTrace.cv?.model as { name?: string } | null | undefined)?.name || '—'}</div>
                    <div>Число кадров-доказательств: {(decisionTrace.expert?.frame_ids || []).length || 0}</div>
                    <div>Повторный анализ кадров не выполняется — только сохранённые факты</div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        {!loading && tab === 'comment' && (commentsSlot || <div className="panel" style={{ padding: 16 }}>Комментарии недоступны</div>)}
      </div>
      <div className="evidence-panel-foot">
        <div className="evidence-actions">
          {onAcknowledge && (
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
          {onVerdict && (
            <>
              <button
                type="button"
                className="primary finish-edit"
                data-tour-id="finding-confirm"
                disabled={verdictBusy || evidence?.lifecycle === 'RESOLVED'}
                onClick={() => onVerdict('confirm')}
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
                data-tour-id="finding-correct"
                disabled={verdictBusy || evidence?.lifecycle === 'RESOLVED'}
                onClick={() => setCorrectOpen((v) => !v)}
              >
                Исправить
              </button>
            </>
          )}
          {onReopen && (evidence?.lifecycle === 'RESOLVED' || evidence?.lifecycle === 'ACKNOWLEDGED') && (
            <button
              type="button"
              className="header-action"
              data-tour-id="finding-reopen"
              disabled={reopenBusy || verdictBusy || acknowledgeBusy}
              onClick={onReopen}
              title="Вернуть предупреждение на проверку, если решение принято по ошибке"
            >
              {reopenBusy ? 'Возвращаю…' : 'Вернуть на проверку'}
            </button>
          )}
        </div>
        {correctOpen && onVerdict && (
          <div className="evidence-correct-form">
            <b>Исправление (ML-метка)</b>
            <label>
              Вид работы (код / название)
              <input
                value={correctWorkType}
                onChange={(e) => setCorrectWorkType(e.target.value)}
                placeholder="например, soil_haulage или excavation"
              />
            </label>
            <label>
              Привязка к строке КСГ (id)
              <input
                value={correctScheduleId}
                onChange={(e) => setCorrectScheduleId(e.target.value)}
                placeholder={evidence?.schedule_item?.id ? String(evidence.schedule_item.id) : 'schedule_item_id'}
              />
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

  if (variant === 'inline') return panel
  return createPortal(panel, document.body)
}
