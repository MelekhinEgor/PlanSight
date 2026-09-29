import {useMemo, useState} from 'react'
import {ChevronLeft, ChevronRight, Download, Search} from 'lucide-react'
import {WORK_TYPES_LTC} from '../admin/workTypesLtc'
import type {MappingDraftRow, MappingOverride} from '../api/client'

/** Порог: ≥85% считаем уверенным и по умолчанию не показываем */
export const HIGH_CONFIDENCE = 0.85

type FilterMode = 'needs' | 'all' | 'matched' | 'unmapped'

type MappingGroup = {
  key: string
  source_name: string
  count: number
  row_indices: number[]
  canonical_work_id: string | null
  canonical_work_code: string | null
  canonical_work_name: string | null
  mapping_status: MappingDraftRow['mapping_status']
  needs_confirmation: boolean
  confidence: number
  candidates: MappingDraftRow['candidates']
}

type Props = {
  rows: MappingDraftRow[]
  filename?: string
  applying?: boolean
  embedded?: boolean
  recognizedCount?: number
  onCancel: () => void
  onApply: (overrides: MappingOverride[]) => void
}

const PAGE_SIZE = 10

export function isUncertainMapping(
  r: Pick<MappingDraftRow, 'canonical_work_id' | 'mapping_status' | 'needs_confirmation' | 'confidence' | 'candidates'>,
  threshold = HIGH_CONFIDENCE,
) {
  if (!r.canonical_work_id) return true
  if (r.mapping_status !== 'MATCHED') return true
  if (r.needs_confirmation) return true
  return (r.confidence ?? r.candidates[0]?.score ?? 0) < threshold
}

function groupKey(name: string) {
  return name.trim().toLowerCase().replace(/\s+/g, ' ')
}

function buildGroups(rows: MappingDraftRow[]): MappingGroup[] {
  const map = new Map<string, MappingDraftRow[]>()
  for (const r of rows) {
    const k = groupKey(r.source_name)
    map.set(k, [...(map.get(k) ?? []), r])
  }
  return [...map.entries()].map(([key, items]) => {
    // Берём самую «слабую» строку группы как представителя
    const sorted = [...items].sort((a, b) => {
      const ua = isUncertainMapping(a) ? 0 : 1
      const ub = isUncertainMapping(b) ? 0 : 1
      if (ua !== ub) return ua - ub
      return (a.confidence ?? 0) - (b.confidence ?? 0)
    })
    const head = sorted[0]
    const candidates = items.reduce((best, cur) => (cur.candidates.length > best.length ? cur.candidates : best), head.candidates)
    return {
      key,
      source_name: head.source_name,
      count: items.length,
      row_indices: items.map(i => i.row_index),
      canonical_work_id: head.canonical_work_id,
      canonical_work_code: head.canonical_work_code,
      canonical_work_name: head.canonical_work_name,
      mapping_status: head.mapping_status,
      needs_confirmation: items.some(i => i.needs_confirmation) || items.some(i => isUncertainMapping(i)),
      confidence: Math.min(...items.map(i => i.confidence ?? i.candidates[0]?.score ?? 0)),
      candidates,
    }
  })
}

export function CanonicalMappingModal({
  rows,
  filename,
  applying,
  embedded,
  recognizedCount,
  onCancel,
  onApply,
}: Props) {
  const [draft, setDraft] = useState(() => rows.map(r => ({...r})))
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<FilterMode>('needs')
  const [page, setPage] = useState(1)

  const catalog = useMemo(
    () => WORK_TYPES_LTC.map(w => ({id: w.id, code: w.code, name: w.name})).sort((a, b) => a.name.localeCompare(b.name, 'ru')),
    [],
  )

  const groups = useMemo(() => buildGroups(draft), [draft])

  const stats = useMemo(() => {
    const uncertainGroups = groups.filter(g => isUncertainMapping(g)).length
    const confidentGroups = groups.length - uncertainGroups
    const uncertainRows = draft.filter(r => isUncertainMapping(r)).length
    return {
      totalRows: draft.length,
      totalGroups: groups.length,
      uncertainGroups,
      confidentGroups,
      uncertainRows,
      confidentRows: draft.length - uncertainRows,
    }
  }, [draft, groups])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const list = groups.filter(g => {
      if (filter === 'needs' && !isUncertainMapping(g)) return false
      if (filter === 'matched' && isUncertainMapping(g)) return false
      if (filter === 'unmapped' && g.canonical_work_id) return false
      if (q && !g.source_name.toLowerCase().includes(q)) return false
      return true
    })
    return list.sort((a, b) => {
      if (!a.canonical_work_id && b.canonical_work_id) return -1
      if (a.canonical_work_id && !b.canonical_work_id) return 1
      return a.confidence - b.confidence
    })
  }, [groups, query, filter])

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage = Math.min(page, pageCount)
  const pageRows = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE)

  const setWorkForGroup = (key: string, workId: string) => {
    const w = workId ? catalog.find(c => c.id === workId) : null
    setDraft(prev =>
      prev.map(r => {
        if (groupKey(r.source_name) !== key) return r
        if (!w) {
          return {
            ...r,
            canonical_work_id: null,
            canonical_work_code: null,
            canonical_work_name: null,
            mapping_status: 'UNMAPPED' as const,
            needs_confirmation: true,
            confidence: 0,
          }
        }
        return {
          ...r,
          canonical_work_id: w.id,
          canonical_work_code: w.code,
          canonical_work_name: w.name,
          mapping_status: 'MATCHED' as const,
          needs_confirmation: false,
          confidence: 1,
        }
      }),
    )
  }

  const downloadCsv = () => {
    const header = ['№', 'Наименование из файла', 'Повторов', 'Код справочника', 'Вид работ из справочника', 'Уверенность', 'Статус']
    const lines = groups.map((g, i) =>
      [
        String(i + 1),
        `"${g.source_name.replace(/"/g, '""')}"`,
        String(g.count),
        g.canonical_work_code ?? '',
        `"${(g.canonical_work_name ?? '').replace(/"/g, '""')}"`,
        `${Math.round(g.confidence * 100)}%`,
        isUncertainMapping(g) ? 'на проверке' : 'уверено',
      ].join(';'),
    )
    const blob = new Blob(['\ufeff' + [header.join(';'), ...lines].join('\n')], {type: 'text/csv;charset=utf-8'})
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `сопоставление_${(filename ?? 'import').replace(/\.[^.]+$/, '')}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  const apply = () => {
    onApply(draft.map(r => ({row_index: r.row_index, canonical_work_id: r.canonical_work_id})))
  }

  const pageButtons = () => {
    const items: number[] = []
    const maxShow = 5
    let start = Math.max(1, safePage - 2)
    let end = Math.min(pageCount, start + maxShow - 1)
    start = Math.max(1, end - maxShow + 1)
    for (let i = start; i <= end; i++) items.push(i)
    return items
  }

  const body = (
    <>
      <div className="preview-kpis mapping-summary-kpis">
        <div className="is-hero">
          <span>Распознано работ</span>
          <b>{recognizedCount ?? stats.totalRows}</b>
        </div>
        <div>
          <span>Уникальных названий</span>
          <b>{stats.totalGroups}</b>
        </div>
        <div>
          <span>На проверку</span>
          <b>{stats.uncertainGroups}</b>
        </div>
      </div>

      <p className="mapping-review-lead">
        Одинаковые названия объединены в одну строку (правка применится ко всем повторам). Показаны сомнительные; уверенные
        (≥{Math.round(HIGH_CONFIDENCE * 100)}%) скрыты — откройте фильтром «Все».
      </p>

      <div className="mapping-table-wrap">
        <table className="mapping-table">
          <thead>
            <tr>
              <th className="col-num">№</th>
              <th>Наименование из файла</th>
              <th>Выбор из справочника</th>
              <th className="col-conf">%</th>
              <th>Вид работ из справочника</th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((g, idx) => {
              const abs = (safePage - 1) * PAGE_SIZE + idx + 1
              const empty = !g.canonical_work_id
              const conf = Math.round(g.confidence * 100)
              const options = (() => {
                const ids = new Set(g.candidates.map(c => c.id))
                const top = g.candidates.map(c => ({id: c.id, name: c.name}))
                const rest = catalog.filter(c => !ids.has(c.id)).slice(0, 80)
                const selected =
                  g.canonical_work_id && !ids.has(g.canonical_work_id) ? catalog.filter(c => c.id === g.canonical_work_id) : []
                return [...top, ...selected, ...rest]
              })()
              return (
                <tr key={g.key} className={empty ? 'is-empty' : 'is-review'}>
                  <td className="col-num">{abs}</td>
                  <td>
                    <span className="mapping-source">{g.source_name}</span>
                    {g.count > 1 && <span className="mapping-count">×{g.count}</span>}
                  </td>
                  <td>
                    <select
                      className={empty ? 'mapping-select is-empty' : 'mapping-select'}
                      value={g.canonical_work_id ?? ''}
                      onChange={e => setWorkForGroup(g.key, e.target.value)}
                    >
                      <option value="">Выберите вид работ из справочника...</option>
                      {options.map(o => (
                        <option key={o.id} value={o.id}>
                          {o.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="col-conf">{empty ? '—' : `${conf}%`}</td>
                  <td>
                    <span className={`mapping-catalog${empty ? ' is-empty' : ''}`}>
                      {g.canonical_work_name ?? '— не сопоставлено —'}
                    </span>
                  </td>
                </tr>
              )
            })}
            {!pageRows.length && (
              <tr>
                <td colSpan={5} className="mapping-empty">
                  {filter === 'needs'
                    ? 'Нет сомнительных строк — все сопоставления уверенные'
                    : 'Нет строк по текущему фильтру'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mapping-toolbar">
        <label className="mapping-search">
          <Search size={14} strokeWidth={1.8} aria-hidden />
          <input
            value={query}
            onChange={e => {
              setQuery(e.target.value)
              setPage(1)
            }}
            placeholder="Поиск по наименованию из файла..."
          />
        </label>
        <label className="mapping-filter">
          <span>Показывать:</span>
          <select
            value={filter}
            onChange={e => {
              setFilter(e.target.value as FilterMode)
              setPage(1)
            }}
          >
            <option value="needs">Сначала сомнительные</option>
            <option value="all">Все уникальные</option>
            <option value="matched">Только уверенные</option>
            <option value="unmapped">Без сопоставления</option>
          </select>
        </label>
        <div className="mapping-pager">
          <span>
            Показано {filtered.length ? (safePage - 1) * PAGE_SIZE + 1 : 0}–
            {Math.min(safePage * PAGE_SIZE, filtered.length)} из {filtered.length} названий
          </span>
          <button type="button" disabled={safePage <= 1} onClick={() => setPage(p => Math.max(1, p - 1))} aria-label="Назад">
            <ChevronLeft size={16} />
          </button>
          {pageButtons().map(n => (
            <button key={n} type="button" className={n === safePage ? 'is-active' : ''} onClick={() => setPage(n)}>
              {n}
            </button>
          ))}
          <button
            type="button"
            disabled={safePage >= pageCount}
            onClick={() => setPage(p => Math.min(pageCount, p + 1))}
            aria-label="Вперёд"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      <div className="mapping-actions">
        <button type="button" className="mapping-download" onClick={downloadCsv}>
          <Download size={15} strokeWidth={1.8} />
          Скачать результат сопоставления
        </button>
        <div className="modal-actions mapping-footer-btns">
          <button type="button" onClick={onCancel} disabled={applying}>
            Отмена
          </button>
          <button type="button" className="primary" disabled={applying} onClick={apply}>
            {applying ? 'Импортирую…' : 'Применить и создать версию'}
          </button>
        </div>
      </div>
    </>
  )

  if (embedded) {
    return <div className="mapping-embedded">{body}</div>
  }

  return (
    <div className="modal-backdrop">
      <div className="import-modal mapping-review-modal">
        <div className="modal-head">
          <div>
            <small>CANONICAL WORK</small>
            <h2>Сопоставление работ со справочником</h2>
          </div>
          <button type="button" onClick={onCancel} aria-label="Закрыть">
            ×
          </button>
        </div>
        {body}
      </div>
    </div>
  )
}
