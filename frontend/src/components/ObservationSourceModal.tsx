import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { DateRuInput } from './DateRuInput'
import { defaultCaptureLocal } from '../labels/ru'

type CameraRow = { id: number; name: string; building_hint?: string | null }

type Props = {
  projectId: string
  cameras: CameraRow[]
  open: boolean
  onClose: () => void
  onDone: (info?: { cameraId?: number; cameraName?: string; frameIds?: number[]; capturedAt?: string }) => void
}

function splitCapture(v: string): { date: string; hour: string; minute: string } {
  const m = v.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/)
  if (!m) {
    const d = defaultCaptureLocal()
    return { date: d.slice(0, 10), hour: d.slice(11, 13), minute: d.slice(14, 16) }
  }
  return { date: m[1], hour: m[2], minute: m[3] }
}

function joinCapture(date: string | null, hour: string, minute: string): string {
  const day = date || defaultCaptureLocal().slice(0, 10)
  return `${day}T${hour.padStart(2, '0')}:${minute.padStart(2, '0')}`
}

const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'))
const MINUTES = Array.from({ length: 12 }, (_, i) => String(i * 5).padStart(2, '0'))

export function ObservationSourceCta({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className="primary finish-edit" onClick={onClick} data-tour-id="observation-source-cta">
      Источник наблюдений
    </button>
  )
}

export function ObservationSourceModal({ projectId, cameras, open, onClose, onDone }: Props) {
  const initial = splitCapture(defaultCaptureLocal())
  const [cameraMode, setCameraMode] = useState<'existing' | 'new'>(cameras.length ? 'existing' : 'new')
  const [cameraId, setCameraId] = useState<number | ''>(cameras[0]?.id ?? '')
  const [cameraName, setCameraName] = useState('Камера наблюдения')
  const [buildingHint, setBuildingHint] = useState('')
  const [captureDate, setCaptureDate] = useState<string | null>(initial.date)
  const [captureHour, setCaptureHour] = useState(initial.hour)
  const [captureMinute, setCaptureMinute] = useState(
    MINUTES.includes(initial.minute) ? initial.minute : '00',
  )
  const [timezone] = useState('Europe/Moscow')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    const next = splitCapture(defaultCaptureLocal())
    setCaptureDate(next.date)
    setCaptureHour(next.hour)
    setCaptureMinute(MINUTES.includes(next.minute) ? next.minute : '00')
    setFile(null)
    setError(null)
    setResult(null)
    setCameraMode(cameras.length ? 'existing' : 'new')
    setCameraId(cameras[0]?.id ?? '')
  }, [open, cameras])

  const capturedAt = useMemo(
    () => joinCapture(captureDate, captureHour, captureMinute),
    [captureDate, captureHour, captureMinute],
  )

  const accept = useMemo(
    () => 'image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.zip,application/zip',
    [],
  )

  if (!open) return null

  async function submit() {
    setError(null)
    setResult(null)
    if (!file) {
      setError('Выберите файл со снимками')
      return
    }
    if (!captureDate) {
      setError('Укажите дату съёмки')
      return
    }
    setBusy(true)
    try {
      const local = `${capturedAt}:00`
      const res = (await api.ingestObservations(projectId, {
        file,
        cameraId: cameraMode === 'existing' && cameraId !== '' ? Number(cameraId) : undefined,
        cameraName: cameraMode === 'new' ? cameraName : undefined,
        buildingHint: buildingHint || undefined,
        capturedAt: local,
        timezone,
      })) as {
        frame_count?: number
        deviations_touched?: number
        camera_name?: string
        camera_id?: number
        frame_ids?: number[]
        mode?: string
      }
      const camLabel = res.camera_name || (cameraMode === 'existing'
        ? cameras.find((c) => c.id === cameraId)?.name
        : cameraName) || '—'
      const stageHint =
        res.mode === 'async' ? ' Этапы: загружено → кадры → CV → аналитика → готово.' : ''
      setResult(
        `Кадр на камере «${camLabel}». Дата съёмки: ${previewRu} (Москва). Загружено: ${res.frame_count ?? 0}. Предупреждений затронуто: ${res.deviations_touched ?? 0}.${stageHint} Откройте эту камеру в списке слева — новый кадр в ленте снизу.`,
      )
      onDone({
        cameraId: res.camera_id ?? (cameraMode === 'existing' && cameraId !== '' ? Number(cameraId) : undefined),
        cameraName: camLabel,
        frameIds: res.frame_ids,
        capturedAt: local,
      })
      window.setTimeout(() => onClose(), 900)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setBusy(false)
    }
  }

  const previewRu = captureDate
    ? `${captureDate.slice(8, 10)}.${captureDate.slice(5, 7)}.${captureDate.slice(0, 4)} ${captureHour}:${captureMinute}`
    : '—'

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="import-modal obs-modal"
        role="dialog"
        aria-label="Загрузка снимков"
        data-tour-id="observation-source-modal"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <div>
            <small>Камеры и зоны</small>
            <h2>Загрузить снимки</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Закрыть">
            ×
          </button>
        </div>

        <div className="obs-modal-body">
          <div className="obs-source-tabs" role="tablist" aria-label="Тип источника">
            <button type="button" className="is-active" role="tab" aria-selected>
              Снимки
            </button>
            <button type="button" disabled title="В работе" role="tab" aria-selected={false}>
              Видео · в работе
            </button>
            <button type="button" disabled title="В работе" role="tab" aria-selected={false}>
              Поток · в работе
            </button>
          </div>

          <div className="obs-field">
            <span className="obs-label">Камера</span>
            <div className="obs-seg">
              <button
                type="button"
                className={cameraMode === 'existing' ? 'is-on' : ''}
                disabled={!cameras.length}
                onClick={() => setCameraMode('existing')}
              >
                Существующая
              </button>
              <button
                type="button"
                className={cameraMode === 'new' ? 'is-on' : ''}
                onClick={() => setCameraMode('new')}
              >
                Новая
              </button>
            </div>
          </div>

          {cameraMode === 'existing' ? (
            <label className="obs-field">
              <span className="obs-label">Выберите камеру</span>
              <select
                value={cameraId}
                onChange={(e) => setCameraId(e.target.value ? Number(e.target.value) : '')}
              >
                {cameras.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <label className="obs-field">
              <span className="obs-label">Название камеры</span>
              <input value={cameraName} onChange={(e) => setCameraName(e.target.value)} />
            </label>
          )}

          <label className="obs-field">
            <span className="obs-label">Корпус / зона (подсказка)</span>
            <input
              value={buildingHint}
              onChange={(e) => setBuildingHint(e.target.value)}
              placeholder="например, Корпус 1.1.2"
            />
          </label>

          <div className="obs-field">
            <span className="obs-label">Дата и время съёмки</span>
            <div className="obs-datetime">
              <DateRuInput value={captureDate} onCommit={setCaptureDate} allowEmpty={false} />
              <div className="obs-time-24" aria-label="Время, 24 часа">
                <select
                  value={captureHour}
                  onChange={(e) => setCaptureHour(e.target.value)}
                  aria-label="Часы"
                >
                  {HOURS.map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
                <span className="obs-time-sep">:</span>
                <select
                  value={captureMinute}
                  onChange={(e) => setCaptureMinute(e.target.value)}
                  aria-label="Минуты"
                >
                  {MINUTES.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <small className="obs-hint">
              {previewRu} · {timezone} · предлагается текущее время (Москва), можно изменить
            </small>
          </div>

          <label className="obs-field">
            <span className="obs-label">Файл (JPG / PNG / ZIP)</span>
            <input type="file" accept={accept} onChange={(e) => setFile(e.target.files?.[0] || null)} />
            {file ? <small className="obs-hint">Выбрано: {file.name}</small> : null}
          </label>

          <p className="obs-note">
            После загрузки система сама проверит качество, выполнит детекцию и обновит предупреждения.
          </p>

          {error ? <div className="obs-alert is-error">{error}</div> : null}
          {result ? <div className="obs-alert is-ok">{result}</div> : null}
        </div>

        <div className="modal-actions obs-modal-actions">
          <button type="button" className="header-action" onClick={onClose}>
            Закрыть
          </button>
          <button type="button" className="primary finish-edit" disabled={busy} onClick={submit}>
            {busy ? 'Загрузка…' : 'Загрузить и проанализировать'}
          </button>
        </div>
      </div>
    </div>
  )
}
