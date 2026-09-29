import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { EQUIPMENT_RU } from '../labels/equipment'
import { fmtRuDateTime, todayCaptionShort, todayIsoMoscow } from '../labels/ru'

export type CamZone = {
  id: number
  zone_key?: string
  name?: string
  polygon_norm?: [number, number][] | number[][]
  binding_status?: string
  zone_status?: string
  building?: string | null
}

export type CamFrame = {
  id: number
  image_url?: string
  captured_at?: string | null
  camera_id?: number
}

export type CamDetection = {
  id: number
  equipment_code?: string
  confidence?: number
  bbox_norm?: { x1: number; y1: number; x2: number; y2: number }
  zone_id?: number | null
}

type Props = {
  projectId: string
  cameras: { id: number; name: string }[]
  zonesByCamera: Record<number, CamZone[]>
  framesByCamera: Record<number, CamFrame[]>
  loadDetections: (frameId: number) => Promise<CamDetection[]>
  onOpenSource?: () => void
  onZonesChanged?: () => void
  focusCameraId?: number | null
  focusFrameId?: number | null
  focusNote?: string | null
}

function statusRu(z: CamZone): { label: string; ok: boolean } {
  const s = (z.binding_status || z.zone_status || '').toUpperCase()
  if (s === 'VERIFIED') return { label: 'Подтверждено', ok: true }
  if (s === 'PROPOSED') return { label: 'Предложено', ok: false }
  if (s === 'DRAFT') return { label: 'Черновик', ok: false }
  if (s === 'UNASSIGNED') return { label: 'Без корпуса', ok: false }
  return { label: 'Без привязки', ok: false }
}

function polyPoints100(poly: CamZone['polygon_norm']): string {
  if (!poly?.length) return ''
  return poly
    .map((p) => {
      const x = (Array.isArray(p) ? Number(p[0]) : 0) * 100
      const y = (Array.isArray(p) ? Number(p[1]) : 0) * 100
      return `${x},${y}`
    })
    .join(' ')
}

function zoneLabelPos(poly: CamZone['polygon_norm']): { left: string; top: string } | null {
  if (!Array.isArray(poly) || !poly.length) return null
  const xs = poly.map((p) => (Array.isArray(p) ? Number(p[0]) : 0))
  const ys = poly.map((p) => (Array.isArray(p) ? Number(p[1]) : 0))
  const cx = ((Math.min(...xs) + Math.max(...xs)) / 2) * 100
  const cy = ((Math.min(...ys) + Math.max(...ys)) / 2) * 100
  return { left: `${cx}%`, top: `${cy}%` }
}

export function CameraWorkspace({
  projectId,
  cameras,
  zonesByCamera,
  framesByCamera,
  loadDetections,
  onOpenSource,
  onZonesChanged,
  focusCameraId,
  focusFrameId,
  focusNote,
}: Props) {
  const qc = useQueryClient()
  const [cameraId, setCameraId] = useState<number | null>(cameras[0]?.id ?? null)
  const activeCam = cameraId ?? cameras[0]?.id ?? null
  const [frameId, setFrameId] = useState<number | null>(null)
  const [showRoi, setShowRoi] = useState(true)
  const [showBbox, setShowBbox] = useState(true)
  const [dets, setDets] = useState<CamDetection[]>([])
  const [note, setNote] = useState('')
  const [editingZoneId, setEditingZoneId] = useState<number | null>(null)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    if (focusCameraId != null && cameras.some((c) => c.id === focusCameraId)) {
      setCameraId(focusCameraId)
    }
  }, [focusCameraId, cameras])

  useEffect(() => {
    if (focusFrameId != null) setFrameId(focusFrameId)
  }, [focusFrameId, focusCameraId])

  useEffect(() => {
    if (focusNote) setNote(focusNote)
  }, [focusNote])

  const frames = framesByCamera[activeCam ?? -1] || []
  const zones = zonesByCamera[activeCam ?? -1] || []
  const activeFrame = useMemo(() => {
    return frames.find((f) => f.id === frameId) || frames[0] || null
  }, [frames, frameId])

  useEffect(() => {
    if (focusFrameId != null && focusCameraId != null && focusCameraId === activeCam) {
      setFrameId(focusFrameId)
      return
    }
    setFrameId(null)
  }, [activeCam, focusCameraId, focusFrameId])

  useEffect(() => {
    setEditingZoneId(null)
  }, [activeCam])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      if (!showBbox || !activeFrame) {
        setDets([])
        return
      }
      try {
        const d = await loadDetections(activeFrame.id)
        if (!cancelled) setDets(d)
      } catch {
        if (!cancelled) setDets([])
      }
    })()
    return () => {
      cancelled = true
    }
  }, [activeFrame?.id, showBbox, loadDetections])

  const verifyMut = useMutation({
    mutationFn: ({ zoneId, building }: { zoneId: number; building: string }) =>
      api.verifyZone(projectId, zoneId, building),
    onSuccess: async (_data, vars) => {
      setNote(`Зона привязана к «${vars.building}»`)
      setEditingZoneId(null)
      onZonesChanged?.()
      await qc.invalidateQueries({ queryKey: ['cameras', projectId] })
    },
    onError: (e: Error) => setNote(e.message || 'Не удалось изменить привязку'),
  })

  const objectsQ = useQuery({
    queryKey: ['project-objects', projectId],
    queryFn: () => api.getProjectObjects(projectId),
  })
  const buildingChoices = useMemo(() => {
    const rows = objectsQ.data ?? []
    const names = rows
      .filter((o) => (o.object_type || '') !== 'stage')
      .map((o) => o.name)
      .filter((n): n is string => Boolean(n && n.trim()))
    return [...new Set(names)].sort((a, b) => a.localeCompare(b, 'ru'))
  }, [objectsQ.data])

  const eqByZone = useMemo(() => {
    const map: Record<string, string[]> = {}
    for (const z of zones) {
      const codes = dets
        .filter((d) => d.zone_id === z.id || (!d.zone_id && zones.length === 1))
        .map((d) => d.equipment_code)
        .filter(Boolean) as string[]
      map[String(z.id)] = [...new Set(codes)].map((c) => EQUIPMENT_RU[c] || c)
    }
    return map
  }, [zones, dets])

  const removeFrame = async () => {
    if (!activeFrame || deleting) return
    if (!window.confirm(`Убрать кадр #${activeFrame.id} из ленты?\nЕсли кадр уже в предупреждении — он только скроется (архив).`)) {
      return
    }
    setDeleting(true)
    try {
      const res = await fetch(`/api/projects/${projectId}/frames/${activeFrame.id}`, { method: 'DELETE' })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error((data as { detail?: string }).detail || 'Ошибка удаления')
      setNote(
        (data as { note_ru?: string }).note_ru ||
          ((data as { action?: string }).action === 'ARCHIVED'
            ? 'Кадр скрыт: он связан с предупреждением.'
            : 'Кадр удалён из ленты.'),
      )
      onZonesChanged?.()
    } catch (e) {
      setNote(e instanceof Error ? e.message : 'Не удалось удалить кадр')
    } finally {
      setDeleting(false)
    }
  }

  if (!cameras.length) {
    return (
      <div className="cam-shell" data-tour-id="camera-workspace">
        <div className="gantt-workspace cam-workspace-panel">
          <div className="empty-state" style={{ minHeight: 280 }}>
            <h2>Нет камер с фото</h2>
            <p>Добавьте снимки через «Источник наблюдений» — камера создастся вместе с загрузкой.</p>
            {onOpenSource && (
              <button type="button" className="primary finish-edit" onClick={onOpenSource} data-tour-id="observation-source-cta">
                Источник наблюдений
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="cam-shell" data-tour-id="camera-workspace">
      <div className="workspace-controlbar cam-controlbar">
        <div className="controlbar-left">
          <label className="scale-select">
            <span>Камера:</span>
            <select
              value={activeCam ?? ''}
              onChange={(e) => setCameraId(Number(e.target.value))}
              aria-label="Камера"
            >
              {cameras.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label className="cam-toggle">
            <input type="checkbox" checked={showRoi} onChange={(e) => setShowRoi(e.target.checked)} />
            ROI
          </label>
          <label className="cam-toggle">
            <input type="checkbox" checked={showBbox} onChange={(e) => setShowBbox(e.target.checked)} />
            Техника
          </label>
        </div>
        <div className="workspace-tools">
          <span className="asof-chip" title="Сегодня (Москва)">
            Сегодня · {todayCaptionShort(todayIsoMoscow())}
          </span>
          {onOpenSource && (
            <button type="button" className="primary finish-edit" onClick={onOpenSource} data-tour-id="observation-source-cta">
              Источник наблюдений
            </button>
          )}
        </div>
      </div>
      {note ? (
        <div className="workspace-message" onClick={() => setNote('')}>
          {note}
          <span>×</span>
        </div>
      ) : null}

      <div className="gantt-workspace cam-workspace-panel">
        <div className="camera-grid stage4-camera-grid">
          <div>
            <div className="camera-image-wrap">
              {activeFrame?.image_url ? (
                <img
                  src={activeFrame.image_url}
                  alt={`Кадр ${activeFrame.id}`}
                  onError={(e) => {
                    e.currentTarget.replaceWith(
                      Object.assign(document.createElement('div'), {
                        className: 'empty-state',
                        style:
                          'min-height:280px;display:flex;align-items:center;justify-content:center;padding:24px;color:#667',
                        textContent: 'Кадр не загрузился (проверьте API :8010 и пути frames/).',
                      }),
                    )
                  }}
                />
              ) : (
                <div className="empty-state" style={{ minHeight: 280 }}>
                  <h2>Нет кадра</h2>
                  <p>Загрузите снимки через «Источник наблюдений». Время съёмки — на дату среза проекта.</p>
                </div>
              )}
              <svg className="zone-overlay" viewBox="0 0 100 100" preserveAspectRatio="none">
                {showRoi &&
                  zones.map((z) => {
                    const pts = polyPoints100(z.polygon_norm)
                    if (!pts) return null
                    const verified = statusRu(z).ok
                    return (
                      <polygon
                        key={z.id}
                        className={`zone-shape ${verified ? 'is-verified' : 'is-proposed'}`}
                        points={pts}
                      />
                    )
                  })}
                {showBbox &&
                  dets.map((d) => {
                    const n = d.bbox_norm
                    if (!n) return null
                    return (
                      <rect
                        key={d.id}
                        className="cam-bbox-norm"
                        x={n.x1 * 100}
                        y={n.y1 * 100}
                        width={(n.x2 - n.x1) * 100}
                        height={(n.y2 - n.y1) * 100}
                      />
                    )
                  })}
              </svg>
              {showRoi &&
                zones.map((z) => {
                  const pos = zoneLabelPos(z.polygon_norm)
                  if (!pos) return null
                  const st = statusRu(z)
                  return (
                    <span
                      key={`lbl-${z.id}`}
                      className={`cam-zone-label ${st.ok ? 'is-ok' : ''}`}
                      style={{ left: pos.left, top: pos.top }}
                    >
                      {z.zone_key || z.name}
                      {z.building ? ` · ${z.building}` : ''}
                      {st.ok ? ' · ок' : ''}
                    </span>
                  )
                })}
              {activeFrame && (
                <div className="cam-frame-meta">
                  <span className="cam-frame-meta-text">
                    Кадр #{activeFrame.id} · {fmtRuDateTime(activeFrame.captured_at)}
                  </span>
                  <div className="cam-frame-meta-actions">
                    <button
                      type="button"
                      className="cam-frame-action is-danger"
                      disabled={deleting}
                      title="Убрать из ленты. Кадры-доказательства только архивируются."
                      onClick={() => void removeFrame()}
                    >
                      {deleting ? 'Удаление…' : 'Удалить'}
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div className="stage4-frame-strip">
              <div className="frames stage4-frames">
                {frames.map((f) => (
                  <button
                    type="button"
                    key={f.id}
                    className={`frame-card${activeFrame?.id === f.id ? ' active' : ''}`}
                    onClick={() => setFrameId(f.id)}
                  >
                    {f.image_url ? <img src={f.image_url} alt="" /> : <span className="frame-card-ph" />}
                    <div>
                      <b>Кадр #{f.id}</b>
                      <span>{fmtRuDateTime(f.captured_at)}</span>
                    </div>
                  </button>
                ))}
                {!frames.length ? <span className="side-note">Нет кадров для этой камеры</span> : null}
              </div>
            </div>
          </div>

          <aside className="camera-side stage4-side">
            <h2>Зоны ROI</h2>
            <p className="side-note">
              Корпус можно назначить и исправить в любой момент. Адресный риск — только при подтверждённой привязке.
            </p>
            {zones.map((z) => {
              const st = statusRu(z)
              const eqList = eqByZone[String(z.id)] || []
              const showPicker = editingZoneId === z.id || !st.ok
              return (
                <div key={z.id} className="cam-zone-block">
                  <div className="camera-fact">
                    <b>
                      {z.zone_key || 'зона'} · {z.name || 'без имени'}
                    </b>
                    <span className={`health-pill ${st.ok ? 'ok' : 'poor'}`}>{st.label}</span>
                  </div>
                  <div className="camera-fact">
                    <span>корпус</span>
                    <b>{z.building || 'не назначен'}</b>
                  </div>
                  <div className="camera-fact">
                    <span>на кадре</span>
                    <b>{eqList.length ? eqList.join(', ') : '—'}</b>
                  </div>

                  <div className="cam-zone-edit">
                    {st.ok && (
                      <button
                        type="button"
                        className={`cam-zone-edit-toggle${editingZoneId === z.id ? ' is-open' : ''}`}
                        onClick={() => setEditingZoneId(editingZoneId === z.id ? null : z.id)}
                      >
                        {editingZoneId === z.id ? 'Скрыть список корпусов' : 'Изменить корпус'}
                      </button>
                    )}
                    {showPicker && (
                      <>
                        <div className="health-buttons">
                          {buildingChoices.length ? (
                            buildingChoices.slice(0, 12).map((b) => {
                              const current = (z.building || '').trim() === b
                              return (
                                <button
                                  key={b}
                                  type="button"
                                  className={current ? 'is-current' : undefined}
                                  disabled={verifyMut.isPending || current}
                                  onClick={() => verifyMut.mutate({ zoneId: z.id, building: b })}
                                  title={current ? 'Уже назначен' : `Назначить «${b}»`}
                                >
                                  {b}
                                </button>
                              )
                            })
                          ) : (
                            <span className="side-note">Нет корпусов в структуре проекта</span>
                          )}
                        </div>
                        <p className="cam-zone-edit-hint">
                          {st.ok
                            ? 'Выберите другой корпус — привязка обновится без потери зоны ROI.'
                            : 'Выберите корпус, чтобы подтвердить привязку зоны.'}
                        </p>
                      </>
                    )}
                  </div>
                  <hr />
                </div>
              )
            })}
            {!zones.length ? (
              <p className="side-note">Зон пока нет — они появятся после загрузки кадров или ручной разметки.</p>
            ) : null}
          </aside>
        </div>
      </div>
    </div>
  )
}
