import { useEffect, useState } from 'react'

type Pred = {
  schedule_item_id: number
  name?: string
  building?: string | null
  ui_status?: string
}

type Preview = {
  schedule_item_id: number
  name?: string
  open_predecessors?: Pred[]
  cascade_recommended?: boolean
  message_ru?: string
}

type Props = {
  projectId: string
  scheduleItemId: string | number
  lifecycle?: string | null
}

/**
 * После confirm предупреждения — закрыть работу КСГ (± предшественники по сети).
 * Даты опубликованного графика не меняются.
 */
export function WorkCompletePanel({ projectId, scheduleItemId, lifecycle }: Props) {
  const life = (lifecycle || '').toUpperCase()
  const canShow = ['CONFIRMED', 'VERIFIED', 'RESOLVED'].includes(life)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [selected, setSelected] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (!canShow || !projectId || !scheduleItemId) {
      setPreview(null)
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const res = await fetch(`/api/projects/${projectId}/schedule-items/${scheduleItemId}/complete-preview`)
        const data = (await res.json()) as Preview
        if (!cancelled && res.ok) {
          setPreview(data)
          setSelected((data.open_predecessors || []).map((p) => p.schedule_item_id))
        }
      } catch {
        if (!cancelled) setPreview(null)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [canShow, projectId, scheduleItemId])

  if (!canShow || !preview) return null

  const preds = preview.open_predecessors || []

  const submit = async (mode: 'work_only' | 'with_selected' | 'with_all') => {
    setBusy(true)
    setMsg('')
    try {
      const body =
        mode === 'with_all'
          ? { close_all_open_predecessors: true }
          : mode === 'with_selected'
            ? { close_all_open_predecessors: false, close_predecessor_ids: selected }
            : { close_all_open_predecessors: false, close_predecessor_ids: [] as number[] }
      const res = await fetch(`/api/projects/${projectId}/schedule-items/${scheduleItemId}/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Не удалось закрыть работу')
      setDone(true)
      setMsg(data.message_ru || 'Работа закрыта. Опубликованный КСГ не изменён.')
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'Ошибка')
    } finally {
      setBusy(false)
    }
  }

  const predWord = (n: number) => {
    const mod10 = n % 10
    const mod100 = n % 100
    if (mod10 === 1 && mod100 !== 11) return 'предшественника'
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return 'предшественника'
    return 'предшественников'
  }

  const primaryLabel =
    preds.length > 0 && selected.length > 0
      ? `Закрыть работу и ${selected.length} ${predWord(selected.length)}`
      : 'Закрыть работу'

  return (
    <div className="evidence-subpanel" data-tour-id="work-complete">
      <b className="evidence-subpanel-title">Закрытие работы по КСГ</b>
      <p className="evidence-subpanel-text">
        {preview.message_ru ||
          'Подтвердите завершение работы. Предшественников можно закрыть только по связям в сети.'}
      </p>
      {preds.length > 0 && !done && (
        <ul className="evidence-subpanel-list">
          {preds.map((p) => (
            <li key={p.schedule_item_id}>
              <label className="cam-check">
                <input
                  type="checkbox"
                  checked={selected.includes(p.schedule_item_id)}
                  onChange={(e) => {
                    setSelected((prev) =>
                      e.target.checked
                        ? [...prev, p.schedule_item_id]
                        : prev.filter((id) => id !== p.schedule_item_id),
                    )
                  }}
                />
                <span>
                  {p.name || `#${p.schedule_item_id}`}
                  {p.building ? ` · ${p.building}` : ''}
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}
      {!done && (
        <div className="evidence-subpanel-actions">
          <button
            type="button"
            className="primary finish-edit"
            disabled={busy}
            onClick={() => void submit(selected.length > 0 ? 'with_selected' : 'work_only')}
          >
            {busy ? 'Сохранение…' : primaryLabel}
          </button>
          {preds.length > 0 && selected.length > 0 && (
            <button
              type="button"
              className="header-action"
              disabled={busy}
              onClick={() => void submit('work_only')}
            >
              Только эту работу
            </button>
          )}
          {preds.length > 0 && selected.length < preds.length && (
            <button
              type="button"
              className="header-action"
              disabled={busy}
              onClick={() => void submit('with_all')}
            >
              Со всеми предшественниками
            </button>
          )}
        </div>
      )}
      {msg ? <p className="evidence-subpanel-text" style={{ marginTop: 8 }}>{msg}</p> : null}
    </div>
  )
}
