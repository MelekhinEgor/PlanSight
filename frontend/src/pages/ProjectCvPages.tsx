import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { AlertTriangle, ArrowLeft } from 'lucide-react'
import { api } from '../api/client'
import { setRemoteProjectId } from '../api/remoteBackend'
import { FindingDrawer, type DecisionTrace, type FindingEvidence } from '../components/FindingDrawer'
import { CameraWorkspace, type CamDetection, type CamFrame, type CamZone } from '../components/CameraWorkspace'
import { ObservationSourceModal } from '../components/ObservationSourceModal'
import { asOfCaption, deviationCodeRu, lifecycleRu, signalKindRu } from '../labels/ru'

/**
 * Hide only lab/fixture/test cameras from the working list.
 * Product PHOTO_ARCHIVE («Архив наблюдений…») must stay visible.
 */
function isLabOrTestCameraName(name: string | null | undefined): boolean {
  const n = (name || '').toLowerCase()
  return /cv\s*lab|synth|fixture|тест-?камер|test-?camera|тест камер/.test(n)
}

export function ProjectCamerasPage() {
  const { projectId = '' } = useParams()
  setRemoteProjectId(projectId)
  const qc = useQueryClient()
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => api.getProject(projectId), enabled: !!projectId })
  const cams = useQuery({
    queryKey: ['cameras', projectId],
    queryFn: () => api.getCameras(projectId),
    enabled: !!projectId,
  })
  const rawCameras = (cams.data as { id: number; name: string; building_hint?: string | null }[] | undefined) || []
  const [zonesByCamera, setZonesByCamera] = useState<Record<number, CamZone[]>>({})
  const [framesByCamera, setFramesByCamera] = useState<Record<number, CamFrame[]>>({})
  const [mediaReady, setMediaReady] = useState(false)
  const [sourceOpen, setSourceOpen] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [focusCameraId, setFocusCameraId] = useState<number | null>(null)
  const [focusFrameId, setFocusFrameId] = useState<number | null>(null)
  const [focusNote, setFocusNote] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setMediaReady(false)
    ;(async () => {
      const zMap: Record<number, CamZone[]> = {}
      const fMap: Record<number, CamFrame[]> = {}
      for (const c of rawCameras) {
        if (isLabOrTestCameraName(c.name)) {
          zMap[c.id] = []
          fMap[c.id] = []
          continue
        }
        try {
          const z = (await api.getZones(projectId, c.id)) as { zones?: CamZone[] }
          zMap[c.id] = z.zones || []
        } catch {
          zMap[c.id] = []
        }
        try {
          const f = (await api.getFrames(projectId, c.id)) as { items?: CamFrame[] }
          fMap[c.id] = f.items || []
        } catch {
          fMap[c.id] = []
        }
      }
      if (!cancelled) {
        setZonesByCamera(zMap)
        setFramesByCamera(fMap)
        setMediaReady(true)
      }
    })()
    return () => { cancelled = true }
  }, [projectId, rawCameras.map(c => c.id).join(','), reloadKey])

  const cameraList = useMemo(() => {
    if (!mediaReady) return []
    return rawCameras.filter((c) => {
      if (isLabOrTestCameraName(c.name)) return false
      const frames = framesByCamera[c.id] || []
      return frames.some((f) => Boolean(f.image_url || (f as { imageUrl?: string }).imageUrl))
    })
  }, [rawCameras, framesByCamera, mediaReady])

  const loadDetections = useCallback(async (frameId: number): Promise<CamDetection[]> => {
    const raw = (await api.getFrameDetections(frameId)) as { detections?: CamDetection[] }
    return raw.detections || []
  }, [])

  const refreshMedia = () => {
    qc.invalidateQueries({ queryKey: ['cameras', projectId] })
    setReloadKey((k) => k + 1)
  }

  const onIngestDone = (info?: { cameraId?: number; cameraName?: string; frameIds?: number[]; capturedAt?: string }) => {
    if (info?.cameraId != null) setFocusCameraId(info.cameraId)
    if (info?.frameIds?.length) setFocusFrameId(info.frameIds[info.frameIds.length - 1])
    const when = info?.capturedAt
      ? `${info.capturedAt.slice(8, 10)}.${info.capturedAt.slice(5, 7)}.${info.capturedAt.slice(0, 4)} ${info.capturedAt.slice(11, 16)}`
      : null
    setFocusNote(
      info?.cameraName
        ? `Снимок добавлен на камеру «${info.cameraName}»${when ? ` · съёмка ${when}` : ''}. Смотрите ленту кадров внизу.`
        : 'Снимок загружен. Выберите камеру в списке слева.',
    )
    refreshMedia()
  }

  return (
    <div className="admin-page cam-page">
      <div className="admin-head cam-page-head">
        <div>
          <h1>Камеры и зоны</h1>
          <p>
            {project.data?.name || projectId} · только камеры с кадрами.
            Служебные и пустые камеры скрыты. Предложенная зона не равна корпусу без подтверждения.
          </p>
        </div>
      </div>
      {!mediaReady ? (
        <div className="cam-shell">
          <div className="gantt-workspace cam-workspace-panel">
            <div className="empty-state" style={{ minHeight: 200 }}>
              <p>Загрузка камер…</p>
            </div>
          </div>
        </div>
      ) : (
        <CameraWorkspace
          projectId={projectId}
          cameras={cameraList}
          zonesByCamera={zonesByCamera}
          framesByCamera={framesByCamera}
          loadDetections={loadDetections}
          onOpenSource={() => setSourceOpen(true)}
          onZonesChanged={refreshMedia}
          focusCameraId={focusCameraId}
          focusFrameId={focusFrameId}
          focusNote={focusNote}
        />
      )}
      <ObservationSourceModal
        projectId={projectId}
        cameras={rawCameras.filter((c) => !isLabOrTestCameraName(c.name))}
        open={sourceOpen}
        onClose={() => setSourceOpen(false)}
        onDone={onIngestDone}
      />
    </div>
  )
}

type DevRow = {
  id: number
  code?: string
  title?: string
  lifecycle?: string
  building?: string
  schedule_item_name?: string
  schedule_item_id?: string
  signal_kind?: string
  explanation_ru?: string
  bucket?: string
  group_count?: number
  demo_primary?: boolean
}

function commentCountLabel(n: number) {
  if (n === 1) return '1 комментарий'
  if (n >= 2 && n <= 4) return `${n} комментария`
  return `${n} комментариев`
}

function lifecycleTone(lc?: string) {
  const v = (lc || '').toUpperCase()
  if (v === 'ACKNOWLEDGED') return 'ack'
  if (v === 'RESOLVED' || v === 'CLOSED') return 'done'
  if (v === 'SUPPRESSED') return 'muted'
  return 'open'
}

export function ProjectDeviationsPage() {
  const { projectId = '' } = useParams()
  setRemoteProjectId(projectId)
  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => api.getProject(projectId), enabled: !!projectId })
  const q = useQuery({
    queryKey: ['deviations', projectId],
    queryFn: () => api.getDeviations(projectId),
    enabled: !!projectId,
  })
  const payload = q.data as {
    items?: DevRow[]
    buckets?: { attention?: DevRow[]; needs_data?: DevRow[]; other?: DevRow[] }
    counts?: { attention?: number; needs_data?: number; other?: number }
  } | undefined
  const [bucket, setBucket] = useState<'attention' | 'needs_data' | 'all'>('attention')
  const [sortKey, setSortKey] = useState<'id' | 'type' | 'source' | 'work' | 'status'>('id')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const allItems = payload?.items || []
  const items = useMemo(() => {
    let list: DevRow[]
    if (bucket === 'attention') list = payload?.buckets?.attention || allItems.filter((d) => d.bucket === 'attention')
    else if (bucket === 'needs_data') list = payload?.buckets?.needs_data || allItems.filter((d) => d.bucket === 'needs_data')
    else list = allItems

    const dir = sortDir === 'asc' ? 1 : -1
    const val = (d: DevRow) => {
      switch (sortKey) {
        case 'id':
          return d.id
        case 'type':
          return deviationCodeRu(d.code || d.title).toLocaleLowerCase('ru')
        case 'source':
          return signalKindRu(d.signal_kind).toLocaleLowerCase('ru')
        case 'work':
          return (d.schedule_item_name || d.building || '').toLocaleLowerCase('ru')
        case 'status':
          return lifecycleRu(d.lifecycle).toLocaleLowerCase('ru')
        default:
          return d.id
      }
    }
    return [...list].sort((a, b) => {
      const av = val(a)
      const bv = val(b)
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
      return String(av).localeCompare(String(bv), 'ru', { numeric: true, sensitivity: 'base' }) * dir
    })
  }, [payload, bucket, allItems, sortKey, sortDir])

  const toggleSort = (key: typeof sortKey) => {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else {
      setSortKey(key)
      setSortDir(key === 'id' ? 'asc' : 'asc')
    }
  }
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const selected = items.find((d) => d.id === selectedId) || allItems.find((d) => d.id === selectedId) || null

  useEffect(() => {
    if (selectedId != null && !items.some((d) => d.id === selectedId)) {
      setSelectedId(items[0]?.id ?? null)
    }
  }, [items, selectedId])

  useEffect(() => {
    setVlmText(null)
    setCommentDraft('')
  }, [selectedId])

  const evidence = useQuery({
    queryKey: ['deviation-evidence', projectId, selectedId],
    queryFn: () => api.getDeviationEvidence(projectId, selectedId!) as Promise<FindingEvidence>,
    enabled: !!projectId && selectedId != null,
  })
  const trace = useQuery({
    queryKey: ['decision-trace', projectId, selectedId],
    queryFn: () => api.getDecisionTrace(projectId, selectedId!) as Promise<DecisionTrace>,
    enabled: !!projectId && selectedId != null,
  })
  const [ackBusy, setAckBusy] = useState(false)
  const [verdictBusy, setVerdictBusy] = useState(false)
  const [reopenBusy, setReopenBusy] = useState(false)
  const [vlmBusy, setVlmBusy] = useState(false)
  const [vlmText, setVlmText] = useState<string | null>(null)
  const [commentDraft, setCommentDraft] = useState('')
  const [commentSaving, setCommentSaving] = useState(false)
  const [commentThread, setCommentThread] = useState<Awaited<ReturnType<typeof api.getEvidenceThread>>>([])
  const aiStatus = useQuery({
    queryKey: ['ai-status'],
    queryFn: () => api.aiStatus() as Promise<{ vlm_ui_enabled?: boolean; llm_enabled?: boolean; ai_mode?: string }>,
    staleTime: 60_000,
  })
  const vlmUiEnabled = Boolean(aiStatus.data?.vlm_ui_enabled && aiStatus.data?.llm_enabled)

  const evidenceId = selected?.schedule_item_id ? String(selected.schedule_item_id) : selectedId != null ? `dev-${selectedId}` : null
  const evidenceSignal: 'DEVIATION' | 'RISK' =
    selected?.signal_kind === 'RISK_FROM_SCHEDULE' ? 'RISK' : 'DEVIATION'

  useEffect(() => {
    if (!evidenceId) {
      setCommentThread([])
      return
    }
    let cancelled = false
    api.getEvidenceThread(evidenceId, evidenceSignal).then((thread) => {
      if (!cancelled) setCommentThread(thread)
    })
    return () => {
      cancelled = true
    }
  }, [evidenceId, evidenceSignal])

  const sendComment = async () => {
    if (!evidenceId || !commentDraft.trim() || commentSaving) return
    setCommentSaving(true)
    try {
      const thread = await api.addEvidenceComment(evidenceId, commentDraft, evidenceSignal)
      setCommentThread(thread)
      setCommentDraft('')
    } finally {
      setCommentSaving(false)
    }
  }

  const discussion = useMemo(
    () => [...commentThread].sort((a, b) => b.at.localeCompare(a.at)),
    [commentThread],
  )

  const acknowledge = async () => {
    if (selectedId == null) return
    setAckBusy(true)
    try {
      await api.patchDeviation(projectId, selectedId, { lifecycle: 'ACKNOWLEDGED' })
      await q.refetch()
      await evidence.refetch()
      window.dispatchEvent(new CustomEvent('plansight:finding-acked', { detail: { id: selectedId } }))
    } finally {
      setAckBusy(false)
    }
  }

  const submitVerdict = async (verdict: 'confirm' | 'reject' | 'correct', correction?: Record<string, unknown>) => {
    if (selectedId == null) return
    setVerdictBusy(true)
    try {
      await api.submitDeviationVerdict(projectId, selectedId, { verdict, correction })
      await q.refetch()
      await evidence.refetch()
    } finally {
      setVerdictBusy(false)
    }
  }

  const reopen = async () => {
    if (selectedId == null) return
    setReopenBusy(true)
    try {
      await api.patchDeviation(projectId, selectedId, { lifecycle: 'OPEN', note: 'rollback_mistaken_decision' })
      await q.refetch()
      await evidence.refetch()
    } finally {
      setReopenBusy(false)
    }
  }

  const runVlmAssist = async () => {
    if (selectedId == null) return
    setVlmBusy(true)
    try {
      const ev = evidence.data as FindingEvidence | undefined
      const res = (await api.vlmAssist({
        finding_code: selected?.code,
        activity_name: selected?.schedule_item_name,
        schedule_item: { id: selected?.schedule_item_id, name: selected?.schedule_item_name },
        frame_ids: (ev?.frames || []).map((f) => f.id),
        observed_equipment: ev?.card?.what_seen,
        missing_equipment: ev?.card?.what_missing,
        limitations: ev?.limitations,
      })) as {
        user_explanation?: string
        scene_summary?: string
        user_note_ru?: string
      }
      setVlmText([res.user_note_ru, res.user_explanation || res.scene_summary].filter(Boolean).join('\n\n'))
    } catch (e) {
      setVlmText(e instanceof Error ? e.message : 'Не удалось получить пояснение')
    } finally {
      setVlmBusy(false)
    }
  }

  const counts = {
    attention:
      payload?.counts?.attention ??
      payload?.buckets?.attention?.length ??
      allItems.filter((d) => d.bucket === 'attention').length,
    needs_data:
      payload?.counts?.needs_data ??
      payload?.buckets?.needs_data?.length ??
      allItems.filter((d) => d.bucket === 'needs_data').length,
    all: allItems.length,
  }

  return (
    <div className="admin-page cam-page dev-page">
      <div className="admin-head cam-page-head">
        <div>
          <h1>Предупреждения</h1>
          <p>
            {project.data?.name || projectId} · производственные риски отдельно от качества данных.
            Здесь же можно просмотреть кадры и принять / отклонить вывод.
          </p>
        </div>
      </div>

      <div className="cam-shell">
        <div className="workspace-controlbar cam-controlbar">
          <div className="controlbar-left">
            <div className="dev-bucket-seg" role="tablist" aria-label="Группы предупреждений">
              <button
                type="button"
                role="tab"
                aria-selected={bucket === 'attention'}
                className={bucket === 'attention' ? 'is-on' : ''}
                onClick={() => setBucket('attention')}
              >
                Требует внимания <b>{counts.attention}</b>
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={bucket === 'needs_data'}
                className={bucket === 'needs_data' ? 'is-on' : ''}
                onClick={() => setBucket('needs_data')}
              >
                Уточнить данные <b>{counts.needs_data}</b>
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={bucket === 'all'}
                className={bucket === 'all' ? 'is-on' : ''}
                onClick={() => setBucket('all')}
              >
                Все <b>{counts.all}</b>
              </button>
            </div>
            <span className="asof-chip">{asOfCaption()}</span>
          </div>
          <div className="workspace-tools">
            <Link to={`/projects/${projectId}/schedule`} className="header-action" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, textDecoration: 'none' }}>
              <ArrowLeft size={14} strokeWidth={1.8} aria-hidden />
              К графику
            </Link>
          </div>
        </div>

        <div className="gantt-workspace cam-workspace-panel dev-workspace" data-tour-id="deviations-table">
          <div className="dev-list-pane">
            {q.isLoading ? (
              <div className="empty-state" style={{ minHeight: 220 }}>
                <p>Загрузка предупреждений…</p>
              </div>
            ) : items.length === 0 ? (
              <div className="empty-state" style={{ minHeight: 220 }}>
                <AlertTriangle size={28} strokeWidth={1.6} aria-hidden />
                <h2>Нет предупреждений</h2>
                <p>В этой группе пока пусто. Загрузите снимки на странице камер или выберите другую группу.</p>
              </div>
            ) : (
              <div className="admin-table-wrap">
                <table className="admin-table dev-table">
                  <thead>
                    <tr>
                      {(
                        [
                          ['id', '№'],
                          ['type', 'Тип'],
                          ['source', 'Источник'],
                          ['work', 'Работа'],
                          ['status', 'Статус'],
                        ] as const
                      ).map(([key, label]) => (
                        <th key={key} aria-sort={sortKey === key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                          <button
                            type="button"
                            className={`dev-sort-btn${sortKey === key ? ' is-active' : ''}`}
                            onClick={() => toggleSort(key)}
                          >
                            {label}
                            <span className="dev-sort-ind" aria-hidden>
                              {sortKey === key ? (sortDir === 'asc' ? '↑' : '↓') : '↕'}
                            </span>
                          </button>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((d) => (
                      <tr
                        key={d.id}
                        className={selectedId === d.id ? 'is-selected' : ''}
                        onClick={() => setSelectedId(d.id)}
                      >
                        <td className="dev-id-cell">
                          {d.id}
                          {d.demo_primary ? <span className="dev-star" title="Основной кейс">★</span> : null}
                          {(d.group_count || 1) > 1 ? <small>×{d.group_count}</small> : null}
                        </td>
                        <td>
                          <b>{deviationCodeRu(d.code || d.title)}</b>
                        </td>
                        <td>{signalKindRu(d.signal_kind)}</td>
                        <td className="dev-work-cell">{d.schedule_item_name || d.building || '—'}</td>
                        <td>
                          <span className={`dev-life life-${lifecycleTone(d.lifecycle)}`}>
                            {lifecycleRu(d.lifecycle)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="dev-detail-pane">
            {selectedId == null ? (
              <div className="empty-state" style={{ minHeight: 280 }}>
                <h2>Выберите предупреждение</h2>
                <p>Откройте строку слева, чтобы просмотреть разбор, кадры и принять или отклонить вывод.</p>
              </div>
            ) : (
              <FindingDrawer
                variant="inline"
                open
                onClose={() => setSelectedId(null)}
                title={selected?.schedule_item_name || 'Предупреждение'}
                subtitle={project.data?.name}
                loading={evidence.isLoading}
                evidence={(evidence.data as FindingEvidence) || null}
                decisionTrace={trace.data || null}
                decisionTraceLoading={trace.isLoading}
                onAcknowledge={acknowledge}
                acknowledgeBusy={ackBusy}
                onVerdict={submitVerdict}
                verdictBusy={verdictBusy}
                onReopen={reopen}
                reopenBusy={reopenBusy}
                onVlmAssist={vlmUiEnabled ? runVlmAssist : undefined}
                vlmBusy={vlmBusy}
                vlmText={vlmUiEnabled ? vlmText : null}
                projectId={projectId}
                editorial={
                  selected
                    ? {
                        title: deviationCodeRu(selected.code),
                        text: selected.explanation_ru || 'Нет текста объяснения',
                        expected: '—',
                        detected: lifecycleRu(selected.lifecycle),
                        rule: selected.signal_kind === 'CV_VERIFIED_FINDING' ? 'Кадры наблюдений' : 'Поля графика',
                        asOf: asOfCaption(),
                      }
                    : null
                }
                commentsSlot={
                  <div className="evidence-comment">
                    <div className="evidence-composer">
                      <label>
                        Комментарий аналитика
                        <textarea
                          rows={4}
                          value={commentDraft}
                          placeholder="Напишите комментарий по этому предупреждению…"
                          onChange={(e) => setCommentDraft(e.target.value)}
                          onKeyDown={(e) => {
                            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') void sendComment()
                          }}
                        />
                      </label>
                      <button
                        type="button"
                        className="primary"
                        disabled={commentSaving || !commentDraft.trim()}
                        onClick={() => void sendComment()}
                      >
                        {commentSaving ? 'Отправляю…' : 'Отправить комментарий'}
                      </button>
                    </div>
                    <div className="evidence-discussion">
                      <div className="evidence-discussion-head">
                        <b>Обсуждение</b>
                        <span>{commentCountLabel(discussion.length)}</span>
                      </div>
                      <div className="evidence-discussion-list">
                        {discussion.map((item) => (
                          <article key={item.id} className={`evidence-msg kind-${item.kind}`}>
                            <span className={`evidence-avatar kind-${item.kind}`}>{item.initials}</span>
                            <div className="evidence-msg-body">
                              <div className="evidence-msg-meta">
                                <div>
                                  <b>{item.author}</b>
                                  <small>{item.role}</small>
                                </div>
                                <time>{api.formatEvidenceCommentAt(item.at)}</time>
                              </div>
                              <p>{item.text}</p>
                            </div>
                          </article>
                        ))}
                        {!discussion.length ? (
                          <p className="evidence-discussion-empty">Пока нет комментариев</p>
                        ) : null}
                      </div>
                    </div>
                  </div>
                }
              />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
