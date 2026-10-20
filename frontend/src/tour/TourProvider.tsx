import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { TrainingMascot } from '../components/TrainingMascot'
import { getTourBridge, runTourActions } from './tourBridge'
import { resetFindingUserDismissed } from './findingDismiss'
import { queryTourTarget } from './tourDom'
import { mascotForStepIndex } from './mascots'
import { buildScenarios, resolveRoute } from './scenarios'
import { TourPointer } from './TourPointer'
import { TourSpotlight, TOUR_EXPAND_EXIT_ID } from './TourSpotlight'
import type { TourFocusBeat, TourProgress, TourScenario, TourStep, TourSuccessCondition } from './types'

/** Во сколько раз дольше держать подсветку/текст в авто-обучении (чтобы успеть прочитать). */
const TOUR_READ_PACE = 1.55

type CoachCorner = 'br' | 'bl' | 'tr' | 'tl'

type TourApi = {
  active: boolean
  paused: boolean
  scenario: TourScenario | null
  step: TourStep | null
  stepIndex: number
  stepCount: number
  focusTarget: string | null
  focusHint: string | null
  /** Авто-режим обучения (демонстрация без обязательных кликов). */
  isCompetition: boolean
  startScenario: (scenarioId: string, projectId: string) => void
  next: () => void
  back: () => void
  skip: () => void
  finish: () => void
  pause: () => void
  resume: () => void
  retryTarget: () => void
  requestExit: () => void
}

function isAutoScenario(sc: TourScenario | null | undefined) {
  return sc?.mode === 'auto'
}

async function waitForTarget(target: string, ms: number): Promise<Element | null> {
  if (target === TOUR_EXPAND_EXIT_ID) return document.body
  const end = Date.now() + ms
  while (Date.now() < end) {
    const el = queryTourTarget(target)
    if (el) return el
    await new Promise((r) => window.setTimeout(r, 100))
  }
  return queryTourTarget(target)
}

function resolveBeatTarget(beat: TourFocusBeat): string | null {
  if (beat.target === TOUR_EXPAND_EXIT_ID) return TOUR_EXPAND_EXIT_ID
  if (queryTourTarget(beat.target)) return beat.target
  if (beat.fallbackTarget && queryTourTarget(beat.fallbackTarget)) return beat.fallbackTarget
  return null
}

/** Плашка обучения не должна перекрывать подсвеченный элемент. */
function coachCornerForTarget(targetId: string | null, preferred: CoachCorner = 'br'): CoachCorner {
  if (!targetId) return preferred
  // Карточка/зум справа — коуч слева, чтобы были видны кнопки и фото
  if (
    targetId.startsWith('finding-') ||
    targetId === 'frame-zoom-modal' ||
    targetId === 'schedule-impact' ||
    targetId === 'schedule-impact-details' ||
    targetId === 'schedule-impact-close' ||
    targetId.startsWith('deviation-') ||
    targetId === 'warnings-pane' ||
    targetId === 'finding-confirm' ||
    targetId === 'finding-reject' ||
    targetId === 'finding-export-docx'
  ) {
    return 'bl'
  }
  const el = queryTourTarget(targetId)
  if (!el) return preferred
  const r = el.getBoundingClientRect()
  const coachW = Math.min(380, window.innerWidth - 36)
  const coachH = 230
  const m = 18
  const boxes: Record<CoachCorner, DOMRect> = {
    br: new DOMRect(window.innerWidth - m - coachW, window.innerHeight - m - coachH, coachW, coachH),
    bl: new DOMRect(m, window.innerHeight - m - coachH, coachW, coachH),
    tr: new DOMRect(window.innerWidth - m - coachW, m, coachW, coachH),
    tl: new DOMRect(m, m, coachW, coachH),
  }
  const hits = (c: CoachCorner) => {
    const b = boxes[c]
    return !(r.right + 8 < b.left || r.left - 8 > b.right || r.bottom + 8 < b.top || r.top - 8 > b.bottom)
  }
  if (!hits(preferred)) return preferred
  for (const c of ['br', 'bl', 'tr', 'tl'] as CoachCorner[]) {
    if (!hits(c)) return c
  }
  return preferred
}

const TourContext = createContext<TourApi | null>(null)

const AUTO_CONDITION_TYPES = new Set(['click', 'route', 'event', 'dwell', 'present', 'auto'])

function isAutoCondition(cond: TourSuccessCondition) {
  return AUTO_CONDITION_TYPES.has(cond.type)
}

function conditionMet(cond: TourSuccessCondition, pathname: string, detail?: { target?: string; event?: string }) {
  switch (cond.type) {
    case 'manual':
    case 'auto':
      return false
    case 'route':
      return pathname.includes(cond.includes)
    case 'click':
      return detail?.target === cond.target
    case 'present':
      return Boolean(queryTourTarget(cond.target))
    case 'event':
      return detail?.event === cond.name
    case 'dwell':
      return false
    default:
      return false
  }
}

function loadProgress(key: string | undefined): TourProgress | null {
  if (!key) return null
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    return JSON.parse(raw) as TourProgress
  } catch {
    return null
  }
}

function saveProgress(key: string | undefined, progress: TourProgress) {
  if (!key) return
  try {
    localStorage.setItem(key, JSON.stringify(progress))
  } catch {
    /* ignore */
  }
}

function sleep(ms: number) {
  return new Promise<void>((r) => window.setTimeout(r, ms))
}

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const on = () => setReduced(mq.matches)
    mq.addEventListener?.('change', on)
    return () => mq.removeEventListener?.('change', on)
  }, [])
  return reduced
}

export function TourProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const reducedMotion = usePrefersReducedMotion()
  const [scenarioId, setScenarioId] = useState<string | null>(null)
  const [projectId, setProjectId] = useState('0')
  const [stepIndex, setStepIndex] = useState(0)
  const [active, setActive] = useState(false)
  const [paused, setPaused] = useState(false)
  const [targetMissing, setTargetMissing] = useState(false)
  const [targetEpoch, setTargetEpoch] = useState(0)
  const [focusTarget, setFocusTarget] = useState<string | null>(null)
  const [focusHint, setFocusHint] = useState<string | null>(null)
  const [pointerTarget, setPointerTarget] = useState<string | null>(null)
  const [confirmExit, setConfirmExit] = useState(false)
  const [coachCorner, setCoachCorner] = useState<CoachCorner>('br')
  const completedRef = useRef<string[]>([])
  const analyticsSnapRef = useRef<unknown>(null)
  const runTokenRef = useRef(0)
  /** Пользователь закрыл карточку находки крестиком — не открывать снова на этом шаге. */
  const userClosedFindingRef = useRef(false)
  const pausedRef = useRef(false)
  const coachCornerRef = useRef<CoachCorner>('br')
  const locationRef = useRef(location)
  const navigateRef = useRef(navigate)
  const nextRef = useRef<() => void>(() => {})

  useEffect(() => {
    coachCornerRef.current = coachCorner
  }, [coachCorner])
  useEffect(() => {
    locationRef.current = location
  }, [location])
  useEffect(() => {
    navigateRef.current = navigate
  }, [navigate])

  const scenarios = useMemo(() => buildScenarios(projectId), [projectId])
  const scenario = scenarios.find((s) => s.id === scenarioId) || null
  const step = scenario?.steps[stepIndex] || null
  const stepCount = scenario?.steps.length || 0
  const isLast = Boolean(scenario && stepIndex + 1 >= scenario.steps.length)
  const isCompetition = isAutoScenario(scenario)

  useEffect(() => {
    pausedRef.current = paused
  }, [paused])

  const clearHighlights = useCallback(() => {
    document.querySelectorAll('.tour-highlight').forEach((n) => n.classList.remove('tour-highlight'))
    setFocusTarget(null)
    setFocusHint(null)
    setPointerTarget(null)
  }, [])

  const restoreAnalytics = useCallback(() => {
    const snap = analyticsSnapRef.current
    if (snap != null) getTourBridge().analytics?.restore(snap)
    analyticsSnapRef.current = null
  }, [])

  const persist = useCallback((sc: TourScenario | null, idx: number, finished: boolean) => {
    if (!sc?.storageKey) return
    const doneIds = finished
      ? sc.steps.map((s) => s.id)
      : [...new Set([...completedRef.current, ...sc.steps.slice(0, idx).map((s) => s.id)])]
    completedRef.current = doneIds
    saveProgress(sc.storageKey, {
      stepIndex: finished ? sc.steps.length : idx,
      completedStepIds: doneIds,
      finished,
      updatedAt: new Date().toISOString(),
    })
  }, [])

    const finish = useCallback(() => {
    runTokenRef.current += 1
    persist(scenario, stepIndex, true)
    // Сначала гасим оверлеи тура — без тяжёлого restore в том же тике
    try {
      getTourBridge().finding?.closeZoom?.()
      getTourBridge().schedule?.resetTourUi?.()
      getTourBridge().schedule?.closeEvidence?.()
      getTourBridge().shell?.closeProfileMenu?.()
    } catch {
      /* ignore */
    }
    getTourBridge().competition = null
    resetFindingUserDismissed()
    setActive(false)
    setPaused(false)
    setScenarioId(null)
    setStepIndex(0)
    setTargetMissing(false)
    setConfirmExit(false)
    setFocusTarget(null)
    setFocusHint(null)
    setPointerTarget(null)
    clearHighlights()
    // Фильтры и маршрут — отложенно, чтобы UI не «троил»
    window.setTimeout(() => {
      try {
        restoreAnalytics()
      } catch {
        /* ignore */
      }
      if (location.pathname !== '/' || location.search) {
        navigate('/', { replace: true })
      }
    }, 80)
  }, [clearHighlights, location.pathname, location.search, navigate, persist, restoreAnalytics, scenario, stepIndex])

  const goToStep = useCallback(
    (sc: TourScenario, idx: number, pid: string) => {
      const s = sc.steps[idx]
      if (!s) {
        finish()
        return
      }
      runTokenRef.current += 1
      setTargetMissing(false)
      setConfirmExit(false)
      setStepIndex(idx)
      // Не подсвечиваем step.target заранее; текст — сразу первого бита (не step.text, иначе дубль)
      setFocusTarget(null)
      setPointerTarget(null)
      setFocusHint(s.focusSequence?.[0]?.text || s.text || null)
      persist(sc, idx, false)
      const route = resolveRoute(s.route, pid)
      const routePath = route.split('?')[0]
      const loc = locationRef.current
      const curPath = loc.pathname
      const curFull = `${loc.pathname}${loc.search}`
      const nav = navigateRef.current
      if (route !== curFull && !curPath.startsWith(routePath.split('?')[0])) {
        nav(route)
      } else if (route.includes('?') && route !== curFull) {
        nav(route)
      }
    },
    [finish, persist],
  )

  const startScenario = useCallback(
    (id: string, pid: string) => {
      const list = buildScenarios(pid)
      const sc = list.find((s) => s.id === id)
      if (!sc) return
      const saved = loadProgress(sc.storageKey)
      const resumeIdx =
        saved && !saved.finished && saved.stepIndex >= 0 && saved.stepIndex < sc.steps.length
          ? saved.stepIndex
          : 0
      completedRef.current = saved?.completedStepIds ?? []
      runTokenRef.current += 1
      setProjectId(pid)
      setScenarioId(id)
      setActive(true)
      setPaused(false)
      setTargetMissing(false)
      setConfirmExit(false)
      setStepIndex(resumeIdx)
      if (isAutoScenario(sc)) {
        analyticsSnapRef.current = getTourBridge().analytics?.snapshot() ?? null
        getTourBridge().competition = {
          developer: getTourBridge().competition?.developer || '',
          projectId: pid,
          activityId: getTourBridge().competition?.activityId ?? null,
          deviationId: getTourBridge().competition?.deviationId ?? null,
          cameraId: getTourBridge().competition?.cameraId ?? null,
        }
      }
      persist(sc, resumeIdx, false)
      const first = sc.steps[resumeIdx]
      navigate(resolveRoute(first.route, pid))
    },
    [navigate, persist],
  )

  const next = useCallback(() => {
    if (!scenario) return
    runTokenRef.current += 1
    setPaused(false)
    if (step) completedRef.current = [...new Set([...completedRef.current, step.id])]
    if (stepIndex + 1 >= scenario.steps.length) {
      finish()
      return
    }
    goToStep(scenario, stepIndex + 1, projectId)
  }, [finish, goToStep, projectId, scenario, step, stepIndex])
  nextRef.current = next

  const back = useCallback(() => {
    if (!scenario || stepIndex <= 0) return
    // Останавливаем автопрогон: иначе шаг сразу доигрывается и next() снова уводит вперёд
    runTokenRef.current += 1
    setPaused(true)
    setFocusHint(null)
    setPointerTarget(null)
    goToStep(scenario, stepIndex - 1, projectId)
  }, [goToStep, projectId, scenario, stepIndex])

  const pause = useCallback(() => setPaused(true), [])
  const resume = useCallback(() => setPaused(false), [])
  const retryTarget = useCallback(() => {
    setTargetMissing(false)
    setTargetEpoch((n) => n + 1)
  }, [])
  const requestExit = useCallback(() => {
    if (isCompetition && !isLast) setConfirmExit(true)
    else finish()
  }, [finish, isCompetition, isLast])

  // Ручное вмешательство → пауза (авто-обучение)
  useEffect(() => {
    if (!active || !isCompetition) return
    const onInteract = (e: Event) => {
      const t = e.target as HTMLElement | null
      if (t?.closest?.('[data-tour-id="tour-coach"]')) return
      if (t?.closest?.('.tour-spotlight-root')) return
      if (t?.closest?.('.tour-pointer')) return
      if (!pausedRef.current) setPaused(true)
    }
    document.addEventListener('pointerdown', onInteract, true)
    document.addEventListener('keydown', onInteract, true)
    return () => {
      document.removeEventListener('pointerdown', onInteract, true)
      document.removeEventListener('keydown', onInteract, true)
    }
  }, [active, isCompetition])

  // Guided highlight (не auto)
  useEffect(() => {
    if (!active || !step?.target || isCompetition) return
    document.querySelectorAll('.tour-highlight').forEach((n) => n.classList.remove('tour-highlight'))
    setTargetMissing(false)
    let cancelled = false
    let highlightTimer: number | undefined
    const waitMs = step.optional ? 8000 : 5000
    const tryHighlight = () => {
      const el = queryTourTarget(step.target)
      if (el) {
        el.classList.add('tour-highlight')
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        setTargetMissing(false)
        return true
      }
      return false
    }
    tryHighlight()
    highlightTimer = window.setInterval(() => {
      if (!cancelled) tryHighlight()
    }, 400)
    const missingTimer = window.setTimeout(() => {
      if (!cancelled && !queryTourTarget(step.target)) setTargetMissing(true)
    }, waitMs)
    return () => {
      cancelled = true
      window.clearTimeout(missingTimer)
      if (highlightTimer) window.clearInterval(highlightTimer)
      document.querySelectorAll('.tour-highlight').forEach((n) => n.classList.remove('tour-highlight'))
    }
  }, [active, step?.target, step?.optional, location.pathname, targetEpoch, isCompetition])

  // Auto-обучение: beat.actions → подсветка → пауза (pausedRef, без перезапуска на pause)
  useEffect(() => {
    if (!active || !step || !isCompetition) return
    const token = ++runTokenRef.current
    let cancelled = false

    const waitWhilePaused = async () => {
      while (pausedRef.current && !cancelled && runTokenRef.current === token) {
        await sleep(120)
      }
    }

    const dwell = async (ms: number) => {
      const end = Date.now() + ms
      while (Date.now() < end) {
        await waitWhilePaused()
        if (cancelled || runTokenRef.current !== token) return false
        await sleep(80)
      }
      return true
    }

    const run = async () => {
      userClosedFindingRef.current = false
      resetFindingUserDismissed()
      setPointerTarget(null)
      // Новая сцена — плашка в правом нижнем углу, пока цель не потребует сдвига
      setCoachCorner('br')
      coachCornerRef.current = 'br'
      // Сразу текст первого бита — не step.text и не null (иначе дубль/пролёт стартового бита)
      const firstBeatText = step.focusSequence?.[0]?.text || step.text || null
      setFocusHint(firstBeatText)
      await waitWhilePaused()
      if (cancelled || runTokenRef.current !== token) return

      if (step.actions?.length) {
        await runTourActions(step.actions, navigate)
        if (cancelled || runTokenRef.current !== token) return
        setFocusHint(firstBeatText)
      }

      const seq: TourFocusBeat[] = step.focusSequence?.length
        ? step.focusSequence
        : step.target
          ? [{ target: step.target, durationMs: step.durationMs || 5200 }]
          : []

      if (!seq.length && step.successCondition.type === 'manual') {
        setFocusTarget(null)
        setFocusHint(null)
        return
      }

      for (const beat of seq) {
        await waitWhilePaused()
        if (cancelled || runTokenRef.current !== token) return

        const beatActions = beat.actions || []
        // Подготовка UI до поиска цели — иначе бит «пролетает» (цель ещё не в DOM)
        const preFocusTypes = new Set([
          'ensureAnalyticsFiltersOpen',
          'openWarningsPanel',
          'closeFinding',
          'closeEvidenceFrame',
          'wait',
          'switchDemoUser',
          'openProfileMenu',
          'closeProfileMenu',
          'openDeviation',
          'showEvidenceFrame',
          'openFindingTab',
          // Сначала действие, потом ждём появившуюся цель — иначе рамка запаздывает к тексту
          'confirmFinding',
          'focusGanttActivity',
          'openSettings',
          'openAdmin',
          'goRoute',
        ])
        const preFocusActions = beatActions.filter((a) => preFocusTypes.has(a.type))
        const postFocusActions = beatActions.filter((a) => !preFocusTypes.has(a.type))
        // Текст и угол коуча сразу — не ждём DOM
        setFocusHint(beat.text ?? null)
        setCoachCorner(coachCornerForTarget(beat.target, 'br'))
        if (preFocusActions.length && !beat.pointer) {
          await runTourActions(preFocusActions, navigate)
          if (cancelled || runTokenRef.current !== token) return
        }

        const waitMs = Math.round((beat.waitForMs ?? (reducedMotion ? 900 : 3200)) * (reducedMotion ? 1 : 1.05))
        // Рамку ставим сразу, как только цель появилась (без ожидания конца таймаута)
        const waitEnd = Date.now() + waitMs
        let resolved: string | null = null
        while (Date.now() < waitEnd) {
          if (cancelled || runTokenRef.current !== token) return
          resolved = resolveBeatTarget(beat)
          if (resolved) {
            setPointerTarget(null)
            setFocusTarget(resolved)
            setCoachCorner(coachCornerForTarget(resolved, 'br'))
            break
          }
          await sleep(70)
        }
        if (!resolved && beat.fallbackTarget) {
          await waitForTarget(beat.fallbackTarget, Math.min(1200, waitMs))
          resolved = resolveBeatTarget(beat)
        }
        if (!resolved) {
          setPointerTarget(null)
          await sleep(reducedMotion ? 60 : 120)
          continue
        }

        setPointerTarget(null)
        setFocusTarget(resolved)
        setFocusHint(beat.text ?? null)
        setCoachCorner(coachCornerForTarget(resolved, 'br'))

        await sleep(reducedMotion ? 60 : 180)
        if (cancelled || runTokenRef.current !== token) return
        resolved = resolveBeatTarget(beat) || resolved
        setFocusTarget(resolved)

        // Остальные действия после текста (фильтры, confirm и т.п.)
        if (postFocusActions.length && !beat.pointer) {
          await runTourActions(postFocusActions, navigate)
          if (cancelled || runTokenRef.current !== token) return
          await sleep(reducedMotion ? 80 : 700)
          const after = resolveBeatTarget(beat)
          if (after) {
            setFocusTarget(after)
            setFocusHint(beat.text ?? null)
          }
        }

        if (beat.pointer) {
          setPointerTarget(resolved)
          await sleep(reducedMotion ? 100 : 700)
          if (cancelled || runTokenRef.current !== token) return
          if (beat.actions?.length) {
            await sleep(reducedMotion ? 40 : 120)
            await runTourActions(beat.actions, navigate)
            if (cancelled || runTokenRef.current !== token) return
            await sleep(reducedMotion ? 100 : 700)
            const afterClick = resolveBeatTarget(beat)
            if (afterClick) {
              setFocusTarget(afterClick)
              setFocusHint(beat.text ?? null)
            }
          }
        }

        const baseMs = beat.durationMs || 4200
        const ms = reducedMotion
          ? Math.min(baseMs, 1200)
          : Math.round(baseMs * TOUR_READ_PACE)
        const ok = await dwell(ms)
        setPointerTarget(null)
        if (!ok) return
      }

      if (cancelled || runTokenRef.current !== token) return
      if (step.successCondition.type === 'manual') {
        setFocusTarget(null)
        setFocusHint(null)
        return
      }
      await waitWhilePaused()
      if (!cancelled && runTokenRef.current === token) nextRef.current()
    }

    void run()
    return () => {
      cancelled = true
      setPointerTarget(null)
    }
    // Не зависим от navigate/next/location.search — иначе openSettings(?section=)
    // перезапускает сцену и вкладка «Файлы» уходит в цикл.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- next/navigate через ref
  }, [active, stepIndex, isCompetition, reducedMotion, step?.id])

  // Guided: click / event
  useEffect(() => {
    if (!active || !step || isCompetition) return
    const cond = step.successCondition
    const onClick = (e: MouseEvent) => {
      if (cond.type !== 'click') return
      const node = (e.target as HTMLElement | null)?.closest?.('[data-tour-id]')
      const id = node?.getAttribute('data-tour-id')
      if (id && conditionMet(cond, location.pathname, { target: id })) {
        const pauseMs = typeof cond.pauseMs === 'number' ? cond.pauseMs : 80
        window.setTimeout(() => next(), Math.max(0, pauseMs))
      }
    }
    const onCustom = (e: Event) => {
      if (conditionMet(cond, location.pathname, { event: (e as CustomEvent).type })) next()
    }
    document.addEventListener('click', onClick, true)
    if (cond.type === 'event') window.addEventListener(cond.name, onCustom)
    return () => {
      document.removeEventListener('click', onClick, true)
      if (cond.type === 'event') window.removeEventListener(cond.name, onCustom)
    }
  }, [active, step, location.pathname, next, isCompetition])

  // Guided: route / present
  useEffect(() => {
    if (!active || !step || isCompetition) return
    if (step.successCondition.type === 'route' && conditionMet(step.successCondition, location.pathname)) {
      const m = location.pathname.match(/^\/projects\/([^/]+)\//)
      if (m?.[1] && m[1] !== projectId) setProjectId(m[1])
      const t = window.setTimeout(() => next(), 120)
      return () => window.clearTimeout(t)
    }
    if (step.successCondition.type === 'present' && conditionMet(step.successCondition, location.pathname)) {
      const t = window.setTimeout(() => next(), 200)
      return () => window.clearTimeout(t)
    }
  }, [active, step, location.pathname, next, projectId, isCompetition])

  // Guided: dwell
  useEffect(() => {
    if (!active || !step || isCompetition || step.successCondition.type !== 'dwell') return
    const cond = step.successCondition
    const minMs = cond.minMs ?? 7000
    const minRatio = cond.minRatio ?? 0.45
    let observer: IntersectionObserver | null = null
    let dwellTimer: number | undefined
    let pollTimer: number | undefined
    let advanced = false
    const clearDwell = () => {
      if (dwellTimer !== undefined) {
        window.clearTimeout(dwellTimer)
        dwellTimer = undefined
      }
    }
    const advance = () => {
      if (advanced) return
      advanced = true
      clearDwell()
      next()
    }
    const attach = (el: Element) => {
      observer = new IntersectionObserver(
        (entries) => {
          const entry = entries[0]
          if (!entry) return
          if (entry.isIntersecting && entry.intersectionRatio >= minRatio) {
            if (dwellTimer === undefined) dwellTimer = window.setTimeout(advance, minMs)
          } else clearDwell()
        },
        { threshold: [0, minRatio, 1] },
      )
      observer.observe(el)
    }
    const el = queryTourTarget(cond.target)
    if (el) attach(el)
    else {
      pollTimer = window.setInterval(() => {
        const found = queryTourTarget(cond.target)
        if (found) {
          if (pollTimer) window.clearInterval(pollTimer)
          pollTimer = undefined
          attach(found)
        }
      }, 300)
    }
    return () => {
      clearDwell()
      if (pollTimer) window.clearInterval(pollTimer)
      observer?.disconnect()
    }
  }, [active, step, location.pathname, next, targetEpoch, isCompetition])

  const api: TourApi = {
    active,
    paused,
    scenario,
    step,
    stepIndex,
    stepCount,
    focusTarget,
    focusHint,
    isCompetition,
    startScenario,
    next,
    back,
    skip: next,
    finish,
    pause,
    resume,
    retryTarget,
    requestExit,
  }

  const auto = step ? isAutoCondition(step.successCondition) : false
  const isDwell = step?.successCondition.type === 'dwell'
  const softMissing = Boolean(targetMissing && step?.optional)
  const spotlightId =
    isCompetition && !isLast ? focusTarget || step?.target || null : isCompetition && focusTarget ? focusTarget : null

  return (
    <TourContext.Provider value={api}>
      {children}
      {active && isCompetition && (
        <>
          <TourSpotlight targetId={spotlightId} pulse dim={Boolean(spotlightId)} reducedMotion={reducedMotion} />
          <TourPointer
            targetId={pointerTarget}
            active={Boolean(pointerTarget) && !paused}
            reducedMotion={reducedMotion}
            startDelayMs={reducedMotion ? 40 : 120}
          />
        </>
      )}
      {active && step && (
        <div
          className={`tour-popover tour-coach${isCompetition ? ` is-auto is-pos-${coachCorner}` : ''}${isLast && isCompetition ? ' is-finale' : ''}`}
          role="dialog"
          aria-label={step.title}
          data-tour-id="tour-coach"
        >
          <div className="tour-coach-hero">
            <TrainingMascot id={step.mascot || mascotForStepIndex(stepIndex)} size={isCompetition ? 64 : 72} />
            <div className="tour-coach-meta">
              <b>
                {String(stepIndex + 1).padStart(2, '0')} / {String(stepCount).padStart(2, '0')}
                {isCompetition ? ' · обучение' : ` · ${scenario?.title}`}
              </b>
              <strong>{step.title}</strong>
            </div>
            <button type="button" className="tour-coach-x" onClick={requestExit} aria-label="Закрыть обучение">
              ×
            </button>
          </div>
          <div className="tour-progress-bar" aria-hidden>
            <i style={{ width: `${Math.round(((stepIndex + (isLast ? 1 : 0.35)) / Math.max(1, stepCount)) * 100)}%` }} />
          </div>
          <p>{focusHint || (step.focusSequence?.length ? '' : step.text)}</p>
          {!isCompetition && <small className="tour-expected">Что сделать: {step.expectedAction}</small>}
          {paused && isCompetition && <p className="tour-status">Пауза — автоматические шаги остановлены</p>}
          {targetMissing && !isCompetition ? (
            <p className={`tour-status${softMissing ? '' : ' is-warn'}`}>
              {step.missingHint || 'Нужный элемент ещё не появился.'}
            </p>
          ) : null}
          {confirmExit ? (
            <div className="tour-exit-confirm">
              <p>Прервать обучение до конца?</p>
              <div className="tour-actions">
                <button type="button" className="tour-btn ghost" onClick={() => setConfirmExit(false)}>
                  Остаться
                </button>
                <button type="button" className="tour-btn" onClick={finish}>
                  Прервать
                </button>
              </div>
            </div>
          ) : (
            <div className="tour-actions">
              <button type="button" className="tour-btn ghost" onClick={back} disabled={stepIndex === 0}>
                Назад
              </button>
              {isCompetition && (
                <button type="button" className="tour-btn ghost" onClick={paused ? resume : pause}>
                  {paused ? 'Продолжить' : 'Пауза'}
                </button>
              )}
              {isLast ? (
                <button type="button" className="tour-btn" onClick={finish} data-tour-id="tour-finish-learning">
                  Завершить обучение
                </button>
              ) : (
                <button type="button" className="tour-btn" onClick={next}>
                  Далее
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </TourContext.Provider>
  )
}

export function useTour() {
  const ctx = useContext(TourContext)
  if (!ctx) throw new Error('useTour requires TourProvider')
  return ctx
}

export function useTourOptional() {
  return useContext(TourContext)
}
