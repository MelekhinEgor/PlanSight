import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { isStroginoProject } from '../tour/demoProject'
import { getTourBridge, registerTourBridge } from '../tour/tourBridge'
import {
  Building2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  FolderKanban,
  ListTree,
  RefreshCw,
  Search,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, type PortfolioRow } from '../api/client'
import { ProjectMap, type ProjectMapPoint } from '../components/ProjectMap'
import { COMPANY_GROUP_OPTIONS } from '../data/companyGroups'
import { projectStatusRu } from '../labels/ru'

const STATUS_OPTIONS: [string, string][] = [
  ['ON_TRACK', 'В норме'],
  ['AT_RISK', 'Риск'],
  ['DELAYED', 'Отставание'],
  ['COMPLETED', 'Завершён'],
]

const DELAYED_SHORTCUT = ['DELAYED', 'AT_RISK'] as const

type Filters = {
  companyGroups: string[]
  developers: string[]
  projects: string[]
  statuses: string[]
  onlyDelayed: boolean
}

type TableTab = 'all' | 'deviations' | 'risk' | 'no_data'
type BarMetric = 'max' | 'works'
type MultiKey = 'companyGroups' | 'developers' | 'projects' | 'statuses'

const initialFilters: Filters = {
  companyGroups: [],
  developers: [],
  projects: [],
  statuses: [],
  onlyDelayed: false,
}

const matchesCompanyGroups = (p: PortfolioRow, groups: string[]) => {
  if (!groups.length) return true
  return groups.some((g) => p.companyGroupId === g || p.companyGroup === g)
}

const projectPassesDraftParents = (p: PortfolioRow, f: Pick<Filters, 'companyGroups' | 'developers'>) => {
  if (!matchesCompanyGroups(p, f.companyGroups)) return false
  if (f.developers.length && !f.developers.includes(p.developer)) return false
  return true
}

const pruneFilters = (f: Filters, allProjects: PortfolioRow[]): Filters => {
  const afterGroups = allProjects.filter((p) => matchesCompanyGroups(p, f.companyGroups))
  const developers = f.developers.filter((d) => afterGroups.some((p) => p.developer === d))
  const afterDevs = afterGroups.filter((p) => !developers.length || developers.includes(p.developer))
  const projects = f.projects.filter((id) => afterDevs.some((p) => p.id === id))
  const statuses = f.statuses.filter((s) => STATUS_OPTIONS.some(([id]) => id === s))
  const onlyDelayed =
    statuses.length === DELAYED_SHORTCUT.length && DELAYED_SHORTCUT.every((s) => statuses.includes(s))
  return { ...f, developers, projects, statuses, onlyDelayed }
}

const filterProjects = (all: PortfolioRow[], f: Filters) =>
  all.filter((p) => {
    if (!matchesCompanyGroups(p, f.companyGroups)) return false
    if (f.developers.length && !f.developers.includes(p.developer)) return false
    if (f.projects.length && !f.projects.includes(p.id)) return false
    if (f.statuses.length && !f.statuses.includes(p.status)) return false
    return true
  })

/** Цвет по позиции на визуальной (capped) шкале рейтинга */
const barColorByCriticality = (visualRatio: number, zero: boolean) => {
  if (zero) return '#2fbf7a'
  if (visualRatio >= 0.85) return '#e44857'
  if (visualRatio >= 0.55) return '#f08a24'
  if (visualRatio >= 0.28) return '#e6b000'
  return '#7eb8e8'
}

/** Шкала рейтинга: при выбросе режем max, чтобы остальные бары оставались сравнимыми */
const buildDeviationScale = (values: number[]) => {
  const sorted = [...values].filter((v) => v > 0).sort((a, b) => b - a)
  const rawMax = Math.max(0, sorted[0] ?? 0)
  const second = sorted[1] ?? 0
  const capped = second > 0 && rawMax >= Math.max(second * 2.2, second + 25)
  // 2-й проект ≈ 70–75% ширины — рейтинг читается, выброс клипится
  const visualRaw = capped
    ? Math.max(second / 0.72, second + Math.max(10, Math.round(second * 0.2)), 20)
    : Math.max(rawMax, 20)
  const max = niceCeil(visualRaw)
  const step =
    max <= 20 ? 5 : max <= 40 ? 10 : max <= 60 ? 10 : max <= 100 ? 20 : Math.max(20, Math.round(max / 5 / 10) * 10)
  const ticks: number[] = []
  for (let t = 0; t <= max; t += step) ticks.push(t)
  if (ticks[ticks.length - 1] !== max) ticks.push(max)
  return { max, ticks, capped, rawMax }
}

const statusLabel = (p: PortfolioRow) => {
  if (p.status === 'DELAYED') return 'Критично'
  if (p.status === 'AT_RISK') return 'Риск'
  if (p.status === 'NO_DATA') return 'Нет данных'
  if (p.problemWorks > 0 || p.maxDeviation > 0) return 'Внимание'
  return projectStatusRu(p.status)
}

const rowPriority = (p: PortfolioRow) => {
  if (p.status === 'DELAYED' || p.maxDeviation > 10) return 'is-critical'
  if (p.status === 'AT_RISK' || p.maxDeviation > 5) return 'is-risk'
  if (p.problemWorks > 0 || p.maxDeviation > 0) return 'is-attention'
  return ''
}

export function AnalyticsPage() {
  const navigate = useNavigate()
  const q = useQuery({
    queryKey: ['portfolio'],
    queryFn: api.getPortfolio,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    refetchOnReconnect: true,
    retry: 2,
  })
  const [filters, setFilters] = useState<Filters>(initialFilters)
  const [tableSearch, setTableSearch] = useState('')
  const [tableTab, setTableTab] = useState<TableTab>('deviations')
  const [barMetric, setBarMetric] = useState<BarMetric>('max')
  const [filtersOpen, setFiltersOpen] = useState(() =>
    typeof window === 'undefined' ? true : window.matchMedia('(min-width: 1100px)').matches,
  )
  const filtersUserToggled = useRef(false)
  const filtersRef = useRef(filters)
  filtersRef.current = filters
  const projects = q.data?.projects ?? []
  const trend = q.data?.trend ?? []

  useEffect(() => {
    if (!projects.length) return
    setFilters((prev) => pruneFilters(prev, projects))
    const demo = projects.find(isStroginoProject)
    if (demo?.developer) {
      getTourBridge().competition = {
        ...(getTourBridge().competition || {
          projectId: String(demo.id),
          activityId: null,
          deviationId: null,
          cameraId: null,
        }),
        developer: demo.developer,
        projectId: String(demo.id),
      }
    }
  }, [projects])

  useEffect(() => {
    return registerTourBridge({
      analytics: {
        ensureFiltersOpen: () => {
          filtersUserToggled.current = true
          // Не дёргать layout, если панель уже открыта
          setFiltersOpen((open) => (open ? open : true))
        },
        setDevelopers: (developers) => {
          // Сбрасываем группы, иначе опция застройщика может пропасть из списка и тур тычет «мимо»
          setFilters((prev) =>
            pruneFilters({ ...prev, companyGroups: [], developers }, projects),
          )
        },
        setOnlyDelayed: (value) => {
          setFilters((prev) =>
            pruneFilters(
              {
                ...prev,
                onlyDelayed: value,
                statuses: value ? [...DELAYED_SHORTCUT] : [],
              },
              projects,
            ),
          )
        },
        setBarMetric: (metric) => setBarMetric(metric),
        snapshot: () => ({ ...filtersRef.current, barMetric }),
        restore: (snap) => {
          const s = snap as Filters & { barMetric?: BarMetric }
          if (!s) return
          setFilters(pruneFilters(s, projects))
          if (s.barMetric) setBarMetric(s.barMetric)
        },
      },
    })
  }, [projects, barMetric])

  useEffect(() => {
    // Сворачиваем в боковую полоску, когда не хватает места под 3 виджета + фильтры
    const mq = window.matchMedia('(min-width: 1100px)')
    const sync = () => {
      if (!filtersUserToggled.current || !mq.matches) {
        if (!mq.matches) filtersUserToggled.current = false
        setFiltersOpen(mq.matches)
      }
    }
    sync()
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])

  const reseedAttempted = useRef(false)
  useEffect(() => {
    if (!q.isFetched || q.isFetching || q.isError) return
    if ((q.data?.projects.length ?? 0) > 0) {
      reseedAttempted.current = false
      return
    }
    if (reseedAttempted.current) return
    reseedAttempted.current = true
    api.resetDemo()
    void q.refetch()
  }, [q.isFetched, q.isFetching, q.isError, q.data?.projects.length, q.refetch])

  const developerOptions = useMemo(() => {
    const list = projects.filter((p) => matchesCompanyGroups(p, filters.companyGroups)).map((p) => p.developer)
    return [...new Set(list)].sort((a, b) => a.localeCompare(b, 'ru')).map((d) => [d, d] as [string, string])
  }, [projects, filters.companyGroups])

  const projectOptions = useMemo(() => {
    return projects
      .filter((p) => projectPassesDraftParents(p, filters))
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name, 'ru'))
      .map((p) => [p.id, p.name] as [string, string])
  }, [projects, filters])

  const rows = useMemo(() => filterProjects(projects, filters), [projects, filters])

  const hasActiveSlicers = useMemo(
    () =>
      filters.companyGroups.length > 0 ||
      filters.developers.length > 0 ||
      filters.projects.length > 0 ||
      filters.statuses.length > 0,
    [filters],
  )

  const tabCounts = useMemo(() => {
    const deviations = rows.filter((p) => p.problemWorks > 0 || p.status === 'DELAYED' || p.status === 'AT_RISK').length
    const risk = rows.filter((p) => p.status === 'AT_RISK').length
    const noData = rows.filter((p) => p.status === 'NO_DATA').length
    return { all: rows.length, deviations, risk, noData }
  }, [rows])

  const visibleRows = useMemo(() => {
    let list = rows
    if (tableTab === 'deviations') {
      list = list.filter((p) => p.problemWorks > 0 || p.status === 'DELAYED' || p.status === 'AT_RISK')
    } else if (tableTab === 'risk') {
      list = list.filter((p) => p.status === 'AT_RISK')
    } else if (tableTab === 'no_data') {
      list = list.filter((p) => p.status === 'NO_DATA')
    }
    const s = tableSearch.trim().toLowerCase()
    if (s) list = list.filter((p) => `${p.name} ${p.developer} ${p.region}`.toLowerCase().includes(s))
    return [...list].sort((a, b) => {
      const score = (p: PortfolioRow) =>
        (p.status === 'DELAYED' ? 1000 : 0) + (p.status === 'AT_RISK' ? 500 : 0) + p.maxDeviation * 10 + p.problemWorks
      return score(b) - score(a)
    })
  }, [rows, tableTab, tableSearch])

  const withDeviations = rows.filter((p) => p.problemWorks > 0 || p.status === 'DELAYED' || p.status === 'AT_RISK').length
  const problemWorks = rows.reduce((s, p) => s + p.problemWorks, 0)
  const totalWorks = rows.reduce((s, p) => s + p.totalWorks, 0)
  const changeSum = rows.reduce((s, p) => s + (p.change || 0), 0)
  const maxProject = rows.reduce<PortfolioRow | null>((best, p) => (!best || p.maxDeviation > best.maxDeviation ? p : best), null)
  const deviationShare = rows.length ? Math.round((withDeviations / rows.length) * 100) : 0
  const problemShare = totalWorks ? Math.round((problemWorks / totalWorks) * 1000) / 10 : 0

  const updatedAt = useMemo(() => {
    const asOf = q.data?.as_of || q.data?.meta?.as_of
    if (asOf) {
      const d = new Date(asOf.includes('T') ? asOf : `${asOf}T12:00:00`)
      if (!Number.isNaN(d.getTime())) {
        return d.toLocaleString('ru-RU', {
          day: '2-digit',
          month: '2-digit',
          year: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        })
      }
    }
    return rows.map((p) => p.lastAnalysis).filter(Boolean).sort().at(-1) || '—'
  }, [q.data?.as_of, q.data?.meta?.as_of, rows])

  const barData = useMemo(() => {
    const sorted = [...rows].sort((a, b) =>
      barMetric === 'max' ? b.maxDeviation - a.maxDeviation : b.problemWorks - a.problemWorks,
    )
    return sorted.slice(0, 5).map((p, i) => {
      const value = barMetric === 'max' ? p.maxDeviation : p.problemWorks
      return {
        id: p.id,
        name: p.name,
        developer: p.developer,
        imageUrl: p.imageUrl ?? null,
        thumbIndex: i,
        value,
        label:
          barMetric === 'max'
            ? value
              ? `+${value}`
              : '0'
            : `${value}`,
        labelTitle:
          barMetric === 'max'
            ? value
              ? `+${value} ${dayWord(value)}`
              : 'Без отклонения'
            : `${value}`,
        zero: value <= 0,
      }
    })
  }, [rows, barMetric])

  const barScale = useMemo(() => buildDeviationScale(barData.map((b) => b.value)), [barData])

  const rankedBars = useMemo(
    () =>
      barData.map((item) => {
        const clipped = !item.zero && item.value > barScale.max
        const visualValue = item.zero ? 0 : Math.min(item.value, barScale.max)
        const visualRatio = visualValue / Math.max(barScale.max, 1)
        const widthPct = item.zero ? 4 : Math.min(100, visualRatio * 100)
        return {
          ...item,
          clipped,
          color: barColorByCriticality(clipped ? 1 : visualRatio, item.zero),
          widthPct,
        }
      }),
    [barData, barScale],
  )

  const trendRange = useMemo(() => {
    const to = parseIsoDate(q.data?.as_of?.slice(0, 10)) || todayMoscowDate()
    const from = new Date(to.getTime())
    from.setDate(from.getDate() - 46)
    return { from, to }
  }, [q.data?.as_of])

  const trendMeta = useMemo(() => {
    const days = daysInclusive(trendRange.from, trendRange.to)
    const grain: TrendGrain = days <= 31 ? 'day' : days <= 93 ? 'week' : 'month'
    return {
      days,
      grain,
      caption:
        grain === 'day'
          ? `По дням · ${formatTrendCaption(trendRange.from, trendRange.to)}`
          : grain === 'week'
            ? `По неделям · ${formatTrendCaption(trendRange.from, trendRange.to)}`
            : `По месяцам · ${formatTrendCaption(trendRange.from, trendRange.to)}`,
    }
  }, [trendRange])

  const trendData = useMemo(() => {
    const axis = buildTrendAxis(trendRange.from, trendRange.to, trendMeta.grain)
    const portfolioProblem = projects.reduce((s, p) => s + p.problemWorks, 0)
    const scale =
      portfolioProblem > 0 ? problemWorks / portfolioProblem : rows.length && projects.length ? rows.length / projects.length : 1

    const apiPoints = trend
      .map((t) => {
        const d = parseTrendApiDay(t.day, trendRange.to)
        if (!d) return null
        return { date: startOfDay(d), value: Math.max(0, Math.round(t.deviations * scale)) }
      })
      .filter((x): x is { date: Date; value: number } => Boolean(x))
      .sort((a, b) => a.date.getTime() - b.date.getTime())

    const endValue = Math.max(0, problemWorks || apiPoints.at(-1)?.value || 20)
    const startValue =
      apiPoints[0]?.value ??
      Math.max(4, Math.round(endValue * 0.55))

    return axis.map((date, i, arr) => {
      const t = arr.length <= 1 ? 1 : i / (arr.length - 1)
      let value: number
      if (apiPoints.length >= 2) {
        value = interpolateTrendValue(apiPoints, date)
      } else if (apiPoints.length === 1) {
        const only = apiPoints[0].value
        value = Math.round(only * (0.7 + t * 0.3))
      } else {
        value = Math.round(startValue + (endValue - startValue) * t + Math.sin(t * Math.PI * 1.4) * Math.max(2, endValue * 0.04))
      }
      if (i === arr.length - 1 && problemWorks) value = problemWorks
      return {
        day: formatTrendTick(date, trendMeta.grain),
        value: Math.max(0, value),
        iso: toIsoDate(date),
      }
    })
  }, [trendRange, trendMeta.grain, trend, problemWorks, projects, rows.length])

  const trendDeltaPct = useMemo(() => {
    if (trendData.length < 2) return 0
    const first = trendData[0].value || 1
    const last = trendData[trendData.length - 1].value
    return Math.round(((last - first) / first) * 1000) / 10
  }, [trendData])

  const trendTickInterval = useMemo(() => {
    const n = trendData.length
    if (n <= 8) return 0
    return Math.max(0, Math.ceil(n / 8) - 1)
  }, [trendData.length])

  const mapPoints = useMemo(() => {
    return rows.map((p) => ({
      id: `p-${p.id}`,
      projectId: p.id,
      name: p.name,
      subtitle: `${p.developer} · ${p.region}`,
      kind: 'project' as const,
      lat: p.lat,
      lng: p.lng,
      status: p.status,
      problemWorks: p.problemWorks,
      maxDeviation: p.maxDeviation,
    })) satisfies ProjectMapPoint[]
  }, [rows])

  const setMultiValues = (key: MultiKey, values: string[]) => {
    setFilters((prev) => {
      const next: Filters = { ...prev, [key]: values }
      if (key === 'statuses') {
        next.onlyDelayed =
          values.length === DELAYED_SHORTCUT.length && DELAYED_SHORTCUT.every((s) => values.includes(s))
      }
      return pruneFilters(next, projects)
    })
  }

  const toggleOnlyDelayed = (checked: boolean) => {
    setFilters((prev) =>
      pruneFilters(
        {
          ...prev,
          onlyDelayed: checked,
          statuses: checked ? [...DELAYED_SHORTCUT] : [],
        },
        projects,
      ),
    )
  }

  const reset = () => {
    setFilters(initialFilters)
    setTableSearch('')
    setTableTab('deviations')
  }

  return (
    <div className={`analytics-screen${filtersOpen ? '' : ' is-filters-collapsed'}`}>
      <aside className={`filter-panel is-card${filtersOpen ? '' : ' is-collapsed'}`} data-tour-id="analytics-filters">
        <div className="filter-card">
          <div className="filter-title">
            <h2>Фильтры</h2>
            <button
              type="button"
              className="filter-collapse-btn"
              aria-expanded={filtersOpen}
              aria-label={filtersOpen ? 'Свернуть фильтры' : 'Развернуть фильтры'}
              onClick={() => {
                filtersUserToggled.current = true
                setFiltersOpen((v) => !v)
              }}
            >
              {filtersOpen ? (
                <ChevronLeft size={16} strokeWidth={2} aria-hidden />
              ) : (
                <ChevronRight size={16} strokeWidth={2} aria-hidden />
              )}
            </button>
          </div>

          {filtersOpen && (
            <div className="filter-card-body">
              <FilterMultiSelect
                icon={ListTree}
                label="Группа компаний"
                emptyLabel="Все группы"
                values={filters.companyGroups}
                onChange={(v) => setMultiValues('companyGroups', v)}
                options={COMPANY_GROUP_OPTIONS}
                defaultOpen
                tourId="analytics-company-groups-filter"
              />
              <div data-tour-id="analytics-developer-filter">
              <FilterMultiSelect
                icon={Building2}
                label="Застройщик"
                emptyLabel="Все застройщики"
                values={filters.developers}
                onChange={(v) => setMultiValues('developers', v)}
                options={developerOptions}
                defaultOpen
                highlightOptionId={getTourBridge().competition?.developer || undefined}
                highlightTourId="analytics-developer-option-demo"
                tourId="analytics-developer-filter-inner"
              />
              </div>
              <FilterMultiSelect
                icon={FolderKanban}
                label="Проект"
                emptyLabel="Все проекты"
                values={filters.projects}
                onChange={(v) => setMultiValues('projects', v)}
                options={projectOptions}
                defaultOpen
                tourId="analytics-projects-filter"
              />
              <FilterMultiSelect
                icon={ClipboardList}
                label="Статус отклонения"
                emptyLabel="Все статусы"
                values={filters.statuses}
                onChange={(v) => setMultiValues('statuses', v)}
                options={STATUS_OPTIONS}
                defaultOpen
                tourId="analytics-status-filter"
              />

              <label className={`filter-delay-toggle${filters.onlyDelayed ? ' is-on' : ''}`} data-tour-id="analytics-only-delayed-filter">
                <span>Только с отставанием</span>
                <input
                  type="checkbox"
                  checked={filters.onlyDelayed}
                  onChange={(e) => toggleOnlyDelayed(e.target.checked)}
                />
                <i />
              </label>

              <div className="filter-actions">
                <button type="button" className="reset-filter" onClick={reset}>
                  <RefreshCw size={14} strokeWidth={2} aria-hidden />
                  Сбросить
                </button>
              </div>
            </div>
          )}
        </div>

        {filtersOpen && (
          <div className="filter-updated is-box">
            <i />
            <span>
              Данные обновлены
              <b>{updatedAt}</b>
            </span>
          </div>
        )}
      </aside>

      <div className="analytics-main">
        <div className="analytics-stage">
          <div className="analytics-hero">
            <div className="analytics-stage-bg" aria-hidden />
            <div className="analytics-stage-veil" aria-hidden />
            <header className="analytics-stage-head">
              <div className="analytics-hero-copy">
                <h1>
                  Все проекты
                  <br />
                  под контролем
                </h1>
                <p>Актуальное состояние строительных объектов, отклонения от графика и ключевые риски</p>
              </div>
              <div className="hero-weather" title="Погода в Москве">
                <span className="hero-weather-icon" aria-hidden>
                  ☀
                </span>
                <span className="hero-weather-temp">+14°</span>
                <span className="hero-weather-meta">Москва · {updatedAt}</span>
              </div>
            </header>
          </div>

          {q.isError && (
            <p className="analytics-live-note is-error">Нет связи с API — показаны последние загруженные данные.</p>
          )}
          {!q.isError && !projects.length && q.isFetched && !q.isFetching && (
            <p className="analytics-live-note is-error">Портфель пуст или ещё не загружен.</p>
          )}

          <div className="kpi-row priority on-stage" data-tour-id="analytics-kpi-row">
            <Kpi
              priority="featured"
              tone="neutral"
              label="Проектов всего"
              value={rows.length}
              delta={`+${Math.max(1, Math.round(rows.length * 0.08) || 1)}`}
              deltaTone="up"
              note={hasActiveSlicers ? 'по текущей выборке' : 'активных проектов'}
            />
            <Kpi
              priority="featured"
              tone="danger"
              label="С отклонениями"
              value={withDeviations}
              delta={`+${Math.max(1, Math.round(withDeviations * 0.15) || 1)}`}
              deltaTone="down"
              note={`${deviationShare}% ${hasActiveSlicers ? 'выборки' : 'от всех проектов'}`}
            />
            <Kpi
              priority="featured"
              tone="neutral"
              label="Работ всего"
              value={totalWorks.toLocaleString('ru-RU')}
              delta="+12%"
              deltaTone="up"
              note={hasActiveSlicers ? 'по текущей выборке' : 'по всем проектам'}
            />
            <Kpi
              priority="featured"
              tone="warn"
              label="Работ с отклонением"
              value={problemWorks.toLocaleString('ru-RU')}
              delta={changeSum ? `+${Math.abs(changeSum)}` : '+18'}
              deltaTone="down"
              note={`${problemShare}% от общего числа`}
            />
            <Kpi
              priority="featured"
              tone="accent"
              label="Макс. отклонение"
              value={maxProject ? `+${maxProject.maxDeviation} ${dayWord(maxProject.maxDeviation)}` : '—'}
              note={maxProject ? maxProject.name : 'Нет данных'}
            />
          </div>
        </div>

        <div className="analytics-widgets">
          <section className={`dash-card deviation-card is-primary${q.isError ? ' is-stale' : ''}`} data-tour-id="analytics-deviations-chart">
            <div className="dash-card-head">
              <div>
                <h2>Отклонения по проектам</h2>
              </div>
              <div className="metric-toggle" role="group" aria-label="Метрика" data-tour-id="analytics-bar-metric">
                <button type="button" className={barMetric === 'max' ? 'active' : ''} onClick={() => setBarMetric('max')}>
                  Дни
                </button>
                <button type="button" className={barMetric === 'works' ? 'active' : ''} onClick={() => setBarMetric('works')}>
                  Работы
                </button>
              </div>
            </div>
            <div className={`deviation-list${barScale.capped ? ' is-capped' : ''}`} role="list">
              <div className="deviation-list-grid" aria-hidden>
                {barScale.ticks.map((t) => (
                  <span key={t} className="deviation-grid-line" style={{ left: `${(t / barScale.max) * 100}%` }} />
                ))}
              </div>
              {rankedBars.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="deviation-row"
                  role="listitem"
                  data-tour-id={isStroginoProject({ id: item.id, name: item.name, developer: item.developer }) ? 'analytics-demo-project' : undefined}
                  onClick={() => navigate(`/projects/${item.id}/schedule`)}
                >
                  <ProjectThumb index={item.thumbIndex} imageUrl={item.imageUrl} />
                  <span className="deviation-meta">
                    <FitLabel as="b" text={item.name} max={11.5} min={7.5} />
                    <FitLabel as="small" text={item.developer} max={9.5} min={7} />
                  </span>
                  <span className={`deviation-track${item.clipped ? ' has-clip' : ''}`}>
                    <span
                      className={`deviation-bar${item.zero ? ' is-zero' : ''}${item.clipped ? ' is-clipped' : ''}`}
                      style={{ width: `${item.widthPct}%`, background: item.color }}
                    />
                  </span>
                  <span
                    className={`deviation-value${item.zero ? ' is-ok' : ''}${item.clipped ? ' is-outlier' : ''}`}
                    style={{ color: item.color }}
                    title={item.labelTitle}
                  >
                    {item.label}
                  </span>
                </button>
              ))}
              {!rankedBars.length && <div className="deviation-empty">Нет данных по отклонениям</div>}
              <div className="deviation-axis" aria-hidden>
                <span className="deviation-axis-spacer" />
                <span className="deviation-axis-spacer" />
                <span className="deviation-axis-scale">
                  {barScale.ticks.map((t) => (
                    <span key={t} style={{ left: `${(t / barScale.max) * 100}%` }}>
                      {barScale.capped && t === barScale.max ? `${t}+` : t}
                    </span>
                  ))}
                </span>
                <span className="deviation-axis-end" />
              </div>
            </div>
          </section>

          <section className={`dash-card trend-card is-primary${q.isError ? ' is-stale' : ''}`}>
            <div className="dash-card-head">
              <div>
                <h2>Динамика проблемных работ</h2>
                <span>{trendMeta.caption}</span>
              </div>
            </div>
            <div className="trend-insight">
              <div>
                <b>{problemWorks.toLocaleString('ru-RU')}</b>
                <span>проблемных работ сейчас</span>
              </div>
              <div className={`trend-delta ${trendDeltaPct >= 0 ? 'is-down' : 'is-up'}`}>
                {trendDeltaPct >= 0 ? '↑' : '↓'} {trendDeltaPct > 0 ? '+' : ''}
                {trendDeltaPct}%
                <small>к началу периода</small>
              </div>
            </div>
            <div className="trend-chart">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={trendData} margin={{ top: 8, right: 10, bottom: 0, left: -8 }}>
                  <defs>
                    <linearGradient id="trendFillFocus" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#e44857" stopOpacity={0.22} />
                      <stop offset="100%" stopColor="#e44857" stopOpacity={0.01} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#f0f4f8" vertical={false} strokeDasharray="3 6" />
                  <XAxis
                    dataKey="day"
                    tick={{ fontSize: 10, fill: '#8a9bb0' }}
                    axisLine={false}
                    tickLine={false}
                    interval={trendTickInterval}
                    minTickGap={12}
                  />
                  <YAxis tick={{ fontSize: 10, fill: '#8a9bb0' }} axisLine={false} tickLine={false} width={28} />
                  <Tooltip
                    contentStyle={{ fontSize: 12, border: '0', borderRadius: 10, boxShadow: '0 8px 24px rgba(20,40,70,.12)' }}
                    labelFormatter={(label, payload) => {
                      const iso = (payload?.[0]?.payload as { iso?: string } | undefined)?.iso
                      const d = iso ? parseIsoDate(iso) : null
                      return d ? formatRuDate(d) : String(label)
                    }}
                    formatter={(val) => [`${Number(val).toLocaleString('ru-RU')}`, 'Проблемных работ']}
                  />
                  <Area
                    type="monotone"
                    dataKey="value"
                    name="Проблемных работ"
                    stroke="#d93b4c"
                    strokeWidth={2.6}
                    fill="url(#trendFillFocus)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="dash-card map-card map-card-aux">
            <div className="dash-card-head">
              <div>
                <h2>Проекты на карте</h2>
                <span>{mapPoints.length} точек на карте</span>
              </div>
            </div>
            <ProjectMap points={mapPoints} onOpenProject={(id) => navigate(`/projects/${id}/schedule`)} />
            <div className="map-legend">
              <span>
                <i className="critical" />
                Критично
              </span>
              <span>
                <i className="high" />
                Риск
              </span>
              <span>
                <i className="normal" />
                В норме
              </span>
            </div>
          </section>
        </div>

        <section className="dash-card portfolio-table-card is-decision" data-tour-id="analytics-projects-table">
          <div className="table-toolbar attention-toolbar">
            <div className="table-toolbar-left">
              <h2>Проекты, требующие внимания</h2>
              <div className="table-tabs" role="tablist">
                <button type="button" className={tableTab === 'deviations' ? 'active' : ''} onClick={() => setTableTab('deviations')}>
                  С отклонениями ({tabCounts.deviations})
                </button>
                <button type="button" className={tableTab === 'risk' ? 'active' : ''} onClick={() => setTableTab('risk')}>
                  Риск ({tabCounts.risk})
                </button>
                <button type="button" className={tableTab === 'all' ? 'active' : ''} onClick={() => setTableTab('all')}>
                  Все ({tabCounts.all})
                </button>
                <button type="button" className={tableTab === 'no_data' ? 'active' : ''} onClick={() => setTableTab('no_data')}>
                  Нет данных ({tabCounts.noData})
                </button>
              </div>
            </div>
            <div className="table-search">
              <SearchIcon />
              <input
                value={tableSearch}
                onChange={(e) => setTableSearch(e.target.value)}
                placeholder="Найти проект…"
              />
            </div>
          </div>
          <div className="portfolio-table-wrap">
            <table className="portfolio-table is-decision">
              <thead>
                <tr>
                  <th>Проект</th>
                  <th>Макс. отклонение</th>
                  <th>Работ с отклонением</th>
                  <th>За 7 дней</th>
                  <th>Статус</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((p, i) => (
                  <tr
                    key={p.id}
                    className={rowPriority(p)}
                    data-tour-id={isStroginoProject(p) ? 'analytics-demo-project' : i === 0 ? 'analytics-project-row' : undefined}
                    onClick={() => navigate(`/projects/${p.id}/schedule`)}
                  >
                    <td>
                      <div className="project-cell">
                        <ProjectThumb index={i} imageUrl={p.imageUrl} />
                        <span>
                          <b>{p.name}</b>
                          <small>
                            {p.developer}
                            {p.region ? ` · ${p.region}` : ''}
                          </small>
                        </span>
                      </div>
                    </td>
                    <td>
                      <b className={p.maxDeviation > 10 ? 'red-number' : p.maxDeviation > 5 ? 'orange-number' : ''}>
                        {p.maxDeviation ? `+${p.maxDeviation} ${dayWord(p.maxDeviation)}` : '—'}
                      </b>
                    </td>
                    <td>
                      <b className={p.problemWorks ? 'red-number' : ''}>{p.problemWorks}</b>
                      <span className="cell-sub">из {p.totalWorks}</span>
                    </td>
                    <td>
                      <span className={`delta-chip ${p.change > 0 ? 'is-down' : p.change < 0 ? 'is-up' : ''}`}>
                        {p.change > 0 ? `↑ +${p.change}` : p.change < 0 ? `↓ ${p.change}` : '—'}
                      </span>
                    </td>
                    <td>
                      <span
                        className={`project-status ${
                          p.status === 'DELAYED'
                            ? 'delayed'
                            : p.status === 'AT_RISK'
                              ? 'at_risk'
                              : p.status === 'NO_DATA'
                                ? 'no_data'
                                : p.problemWorks > 0 || p.maxDeviation > 0
                                  ? 'attention'
                                  : p.status.toLowerCase()
                        }`}
                      >
                        <i />
                        {statusLabel(p)}
                      </span>
                    </td>
                    <td className="arrow-cell">Открыть →</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!visibleRows.length && <div className="table-empty">Нет проектов по выбранным условиям</div>}
          </div>
        </section>
      </div>
    </div>
  )
}

function dayWord(n: number) {
  const m = n % 100
  if (m >= 11 && m <= 14) return 'дней'
  const d = n % 10
  return d === 1 ? 'день' : d >= 2 && d <= 4 ? 'дня' : 'дней'
}

type TrendGrain = 'day' | 'week' | 'month'

function todayMoscowDate() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Moscow',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value || '01'
  return parseIsoDate(`${get('year')}-${get('month')}-${get('day')}`) || new Date()
}

function parseIsoDate(value?: string | null) {
  if (!value) return null
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value.trim())
  if (!m) return null
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  return Number.isNaN(d.getTime()) ? null : startOfDay(d)
}

function startOfDay(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate())
}

function toIsoDate(d: Date) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function daysInclusive(from: Date, to: Date) {
  const a = startOfDay(from).getTime()
  const b = startOfDay(to).getTime()
  return Math.max(1, Math.round((b - a) / 86_400_000) + 1)
}

function addDays(d: Date, n: number) {
  const x = new Date(d.getTime())
  x.setDate(x.getDate() + n)
  return startOfDay(x)
}

function formatRuDate(d: Date) {
  const dd = String(d.getDate()).padStart(2, '0')
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  return `${dd}.${mm}.${d.getFullYear()}`
}

function formatTrendCaption(from: Date, to: Date) {
  const sameYear = from.getFullYear() === to.getFullYear()
  if (sameYear) {
    const a = `${String(from.getDate()).padStart(2, '0')}.${String(from.getMonth() + 1).padStart(2, '0')}`
    const b = `${String(to.getDate()).padStart(2, '0')}.${String(to.getMonth() + 1).padStart(2, '0')}`
    return `${a} — ${b}`
  }
  return `${formatRuDate(from)} — ${formatRuDate(to)}`
}

function formatTrendTick(d: Date, grain: TrendGrain) {
  if (grain === 'month') {
    return d.toLocaleDateString('ru-RU', { month: 'short', year: '2-digit' }).replace('.', '')
  }
  return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}`
}

function buildTrendAxis(from: Date, to: Date, grain: TrendGrain) {
  const start = startOfDay(from)
  const end = startOfDay(to)
  const points: Date[] = []

  if (grain === 'day') {
    for (let d = start; d.getTime() <= end.getTime(); d = addDays(d, 1)) points.push(d)
    return points.length ? points : [end]
  }

  if (grain === 'week') {
    points.push(start)
    let cursor = addDays(start, 7)
    while (cursor.getTime() < end.getTime()) {
      points.push(cursor)
      cursor = addDays(cursor, 7)
    }
    if (points[points.length - 1].getTime() !== end.getTime()) points.push(end)
    return points
  }

  points.push(start)
  let cursor = new Date(start.getFullYear(), start.getMonth() + 1, 1)
  while (cursor.getTime() < end.getTime()) {
    points.push(startOfDay(cursor))
    cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1)
  }
  if (points[points.length - 1].getTime() !== end.getTime()) points.push(end)
  return points
}

/** Парсит day из API: ISO, dd.MM, «17 сен», «17 Sep» */
function parseTrendApiDay(raw: string, anchor: Date) {
  const iso = parseIsoDate(raw)
  if (iso) return iso
  const dotted = /^(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?$/.exec(raw.trim())
  if (dotted) {
    const year = dotted[3]
      ? dotted[3].length === 2
        ? 2000 + Number(dotted[3])
        : Number(dotted[3])
      : anchor.getFullYear()
    return startOfDay(new Date(year, Number(dotted[2]) - 1, Number(dotted[1])))
  }
  const months: Record<string, number> = {
    янв: 0,
    фев: 1,
    мар: 2,
    апр: 3,
    май: 4,
    июн: 5,
    июл: 6,
    авг: 7,
    сен: 8,
    окт: 9,
    ноя: 10,
    дек: 11,
    jan: 0,
    feb: 1,
    mar: 2,
    apr: 3,
    may: 4,
    jun: 5,
    jul: 6,
    aug: 7,
    sep: 8,
    oct: 9,
    nov: 10,
    dec: 11,
  }
  const m = /^(\d{1,2})\s+([A-Za-zА-Яа-яё]{3})/u.exec(raw.trim())
  if (!m) return null
  const mon = months[m[2].toLowerCase().slice(0, 3)]
  if (mon == null) return null
  return startOfDay(new Date(anchor.getFullYear(), mon, Number(m[1])))
}

function interpolateTrendValue(points: { date: Date; value: number }[], at: Date) {
  const t = at.getTime()
  if (t <= points[0].date.getTime()) return points[0].value
  if (t >= points[points.length - 1].date.getTime()) return points[points.length - 1].value
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i]
    const b = points[i + 1]
    if (t >= a.date.getTime() && t <= b.date.getTime()) {
      const span = Math.max(1, b.date.getTime() - a.date.getTime())
      const r = (t - a.date.getTime()) / span
      return Math.round(a.value + (b.value - a.value) * r)
    }
  }
  return points[points.length - 1].value
}

function niceCeil(n: number) {
  if (n <= 0) return 20
  if (n <= 20) return 20
  if (n <= 25) return 25
  if (n <= 30) return 30
  if (n <= 40) return 40
  if (n <= 50) return 50
  if (n <= 60) return 60
  if (n <= 80) return 80
  if (n <= 100) return 100
  if (n <= 150) return 150
  if (n <= 200) return 200
  const mag = 10 ** Math.floor(Math.log10(n))
  return Math.ceil(n / mag) * mag
}

function Kpi({
  priority,
  tone,
  label,
  value,
  delta,
  deltaTone,
  note,
}: {
  priority: 'featured' | 'muted'
  tone: string
  label: string
  value: string | number
  delta?: string
  deltaTone?: 'up' | 'down'
  note?: string
}) {
  return (
    <div className={`kpi-card priority-${priority} tone-${tone}`}>
      <span className="kpi-label">
        <i className="kpi-accent" aria-hidden />
        {label}
      </span>
      <div className="kpi-value-row">
        <strong>{value}</strong>
        {delta ? <small className={deltaTone === 'up' ? 'positive-note' : 'negative-note'}>{delta}</small> : null}
      </div>
      {note ? <span className="kpi-note">{note}</span> : null}
    </div>
  )
}

function FilterMultiSelect({
  icon: Icon,
  label,
  emptyLabel,
  values,
  onChange,
  options,
  defaultOpen = false,
  highlightOptionId,
  highlightTourId,
  tourId,
}: {
  icon?: LucideIcon
  label: string
  emptyLabel: string
  values: string[]
  onChange: (v: string[]) => void
  options: [string, string][]
  defaultOpen?: boolean
  highlightOptionId?: string
  highlightTourId?: string
  tourId?: string
}) {
  const [open, setOpen] = useState(defaultOpen)
  const [query, setQuery] = useState('')

  const selected = useMemo(() => new Set(values), [values])
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options
    return options.filter(([, name]) => name.toLowerCase().includes(q))
  }, [options, query])

  useEffect(() => {
    if (highlightOptionId) setOpen(true)
  }, [highlightOptionId])

  useEffect(() => {
    if (!open || !highlightTourId) return
    const el = document.querySelector(`[data-tour-id="${highlightTourId}"]`)
    if (el instanceof HTMLElement) {
      window.requestAnimationFrame(() => {
        el.scrollIntoView({ block: 'nearest', inline: 'nearest' })
      })
    }
  }, [open, highlightTourId, highlightOptionId, filtered])

  const allVisibleIds = filtered.map(([id]) => id)
  const allVisibleSelected = allVisibleIds.length > 0 && allVisibleIds.every((id) => selected.has(id))

  const summary =
    values.length === 0 ? 'Все' : values.length === 1 ? '1 выбрано' : `${values.length} выбрано`

  const toggle = (id: string) => {
    if (selected.has(id)) onChange(values.filter((v) => v !== id))
    else onChange([...values, id])
  }

  const toggleAllVisible = () => {
    if (allVisibleSelected) {
      const drop = new Set(allVisibleIds)
      onChange(values.filter((v) => !drop.has(v)))
      return
    }
    const next = new Set(values)
    for (const id of allVisibleIds) next.add(id)
    onChange([...next])
  }

  return (
    <div
      className={`filter-accordion${open ? ' is-open' : ''}${values.length ? ' has-selection' : ''}`}
      data-tour-id={tourId}
    >
      <button
        type="button"
        className="filter-accordion-head"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="filter-accordion-title">
          {Icon ? <Icon size={13} strokeWidth={1.8} aria-hidden /> : null}
          {label}
        </span>
        <span className="filter-accordion-meta">
          <span className={values.length ? 'is-filled' : ''}>{summary}</span>
          <ChevronDown size={13} strokeWidth={2} aria-hidden />
        </span>
      </button>
      {open && (
        <div className="filter-accordion-body" role="listbox" aria-multiselectable aria-label={label}>
          <label className="filter-slicer-search">
            <Search size={12} strokeWidth={2} aria-hidden />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Поиск…"
              aria-label={`Поиск: ${label}`}
            />
          </label>
          <button type="button" className="filter-slicer-all" onClick={toggleAllVisible}>
            <span className={`filter-slicer-check${allVisibleSelected ? ' is-on' : ''}`} aria-hidden />
            Выбрать все
          </button>
          <div className="filter-slicer-list">
            {filtered.map(([id, name]) => {
              const on = selected.has(id)
              const isDemoOpt = Boolean(highlightOptionId && highlightTourId && id === highlightOptionId)
              return (
                <button
                  key={id}
                  type="button"
                  role="option"
                  aria-selected={on}
                  className={`filter-slicer-option${on ? ' is-on' : ''}`}
                  data-tour-id={isDemoOpt ? highlightTourId : undefined}
                  onClick={() => toggle(id)}
                >
                  <span className={`filter-slicer-check${on ? ' is-on' : ''}`} aria-hidden />
                  <span title={name}>{name}</span>
                </button>
              )
            })}
            {!filtered.length && <div className="filter-slicer-empty">Нет значений</div>}
          </div>
        </div>
      )}
      <span className="sr-only">{emptyLabel}</span>
    </div>
  )
}

function FitLabel({
  as: Tag,
  text,
  max,
  min,
}: {
  as: 'b' | 'small'
  text: string
  max: number
  min: number
}) {
  const ref = useRef<HTMLElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const fit = () => {
      let size = max
      el.style.fontSize = `${size}px`
      // Сначала даём layout при max, затем уменьшаем пока текст влезает
      while (el.scrollWidth > el.clientWidth + 0.5 && size > min) {
        size = Math.round((size - 0.5) * 10) / 10
        el.style.fontSize = `${size}px`
      }
    }

    fit()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(fit) : null
    ro?.observe(el)
    return () => ro?.disconnect()
  }, [text, max, min])

  return (
    <Tag ref={ref as never} title={text} className="fit-label">
      {text}
    </Tag>
  )
}

function ProjectThumb({ index, imageUrl }: { index: number; imageUrl?: string | null }) {
  if (imageUrl) {
    return (
      <span className="project-thumb has-image">
        <img src={imageUrl} alt="" />
      </span>
    )
  }
  return (
    <span className={`project-thumb thumb-${index % 4}`}>
      <svg viewBox="0 0 28 28" aria-hidden="true">
        <path d="M5 23V10l8-5 10 4v14H5Z" fill="currentColor" opacity=".25" />
        <path
          d="M8 21v-9h4v9M15 21V9h5v12M9 14h2m5-2h3m-3 3h3m-3 3h3"
          stroke="currentColor"
          strokeWidth="1.4"
          fill="none"
          strokeLinecap="round"
        />
      </svg>
    </span>
  )
}

function SearchIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
      <circle cx="7" cy="7" r="4.5" stroke="currentColor" />
      <path d="m10.5 10.5 3 3" stroke="currentColor" strokeLinecap="round" />
    </svg>
  )
}
