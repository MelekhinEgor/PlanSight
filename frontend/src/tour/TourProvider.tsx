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
import { buildScenarios, resolveRoute } from './scenarios'
import type { TourProgress, TourScenario, TourStep, TourSuccessCondition } from './types'

type TourApi = {
  active: boolean
  scenario: TourScenario | null
  step: TourStep | null
  stepIndex: number
  stepCount: number
  startScenario: (scenarioId: string, projectId: string) => void
  next: () => void
  back: () => void
  skip: () => void
  finish: () => void
  retryTarget: () => void
}

const TourContext = createContext<TourApi | null>(null)

const AUTO_CONDITION_TYPES = new Set(['click', 'route', 'event', 'dwell', 'present'])

function isAutoCondition(cond: TourSuccessCondition) {
  return AUTO_CONDITION_TYPES.has(cond.type)
}

function conditionMet(cond: TourSuccessCondition, pathname: string, detail?: { target?: string; event?: string }) {
  switch (cond.type) {
    case 'manual':
      return false
    case 'route':
      return pathname.includes(cond.includes)
    case 'click':
      return detail?.target === cond.target
    case 'present':
      return Boolean(document.querySelector(`[data-tour-id="${cond.target}"]`))
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
    /* игнорировать квоту */
  }
}

function queryTourTarget(target: string) {
  return document.querySelector(`[data-tour-id="${target}"]`)
}

export function TourProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [scenarioId, setScenarioId] = useState<string | null>(null)
  const [projectId, setProjectId] = useState('0')
  const [stepIndex, setStepIndex] = useState(0)
  const [active, setActive] = useState(false)
  const [targetMissing, setTargetMissing] = useState(false)
  const [targetEpoch, setTargetEpoch] = useState(0)
  const completedRef = useRef<string[]>([])

  const scenarios = useMemo(() => buildScenarios(projectId), [projectId])
  const scenario = scenarios.find((s) => s.id === scenarioId) || null
  const step = scenario?.steps[stepIndex] || null
  const stepCount = scenario?.steps.length || 0
  const isLast = Boolean(scenario && stepIndex + 1 >= scenario.steps.length)

  const persist = useCallback(
    (sc: TourScenario | null, idx: number, finished: boolean) => {
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
    },
    [],
  )

  const finish = useCallback(() => {
    persist(scenario, stepIndex, true)
    setActive(false)
    setScenarioId(null)
    setStepIndex(0)
    setTargetMissing(false)
    document.querySelectorAll('.tour-highlight').forEach((n) => n.classList.remove('tour-highlight'))
  }, [persist, scenario, stepIndex])

  const goToStep = useCallback(
    (sc: TourScenario, idx: number, pid: string) => {
      const s = sc.steps[idx]
      if (!s) {
        finish()
        return
      }
      setTargetMissing(false)
      setStepIndex(idx)
      persist(sc, idx, false)
      const route = resolveRoute(s.route, pid)
      const routePath = route.split('?')[0]
      if (!location.pathname.startsWith(routePath) && route !== location.pathname) {
        navigate(route)
      }
    },
    [finish, location.pathname, navigate, persist],
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
      setProjectId(pid)
      setScenarioId(id)
      setActive(true)
      setTargetMissing(false)
      setStepIndex(resumeIdx)
      persist(sc, resumeIdx, false)
      const first = sc.steps[resumeIdx]
      navigate(resolveRoute(first.route, pid))
    },
    [navigate, persist],
  )

  const next = useCallback(() => {
    if (!scenario) return
    if (step) {
      completedRef.current = [...new Set([...completedRef.current, step.id])]
    }
    if (stepIndex + 1 >= scenario.steps.length) {
      finish()
      return
    }
    goToStep(scenario, stepIndex + 1, projectId)
  }, [finish, goToStep, projectId, scenario, step, stepIndex])

  const back = useCallback(() => {
    if (!scenario || stepIndex <= 0) return
    goToStep(scenario, stepIndex - 1, projectId)
  }, [goToStep, projectId, scenario, stepIndex])

  const retryTarget = useCallback(() => {
    setTargetMissing(false)
    setTargetEpoch((n) => n + 1)
  }, [])

  // Подсветка цели + watchdog при пропаже target
  useEffect(() => {
    document.querySelectorAll('.tour-highlight').forEach((n) => n.classList.remove('tour-highlight'))
    if (!active || !step?.target) return

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
      if (cancelled) return
      tryHighlight()
    }, 400)

    const missingTimer = window.setTimeout(() => {
      if (cancelled) return
      if (!queryTourTarget(step.target)) {
        setTargetMissing(true)
        if (import.meta.env.DEV) {
          console.warn(`[tour] target missing after ${waitMs}ms: data-tour-id="${step.target}"`)
        }
      }
    }, waitMs)

    return () => {
      cancelled = true
      window.clearTimeout(missingTimer)
      if (highlightTimer) window.clearInterval(highlightTimer)
      document.querySelectorAll('.tour-highlight').forEach((n) => n.classList.remove('tour-highlight'))
    }
  }, [active, step?.target, step?.optional, location.pathname, targetEpoch])

  // Успех по клику / custom event
  useEffect(() => {
    if (!active || !step) return
    const cond = step.successCondition

    const onClick = (e: MouseEvent) => {
      if (cond.type !== 'click') return
      const node = (e.target as HTMLElement | null)?.closest?.('[data-tour-id]')
      const id = node?.getAttribute('data-tour-id')
      if (id && conditionMet(cond, location.pathname, { target: id })) {
        const pause = typeof cond.pauseMs === 'number' ? cond.pauseMs : 80
        window.setTimeout(() => next(), Math.max(0, pause))
      }
    }

    const onCustom = (e: Event) => {
      const name = (e as CustomEvent).type
      if (conditionMet(cond, location.pathname, { event: name })) next()
    }

    document.addEventListener('click', onClick, true)
    if (cond.type === 'event') window.addEventListener(cond.name, onCustom)
    return () => {
      document.removeEventListener('click', onClick, true)
      if (cond.type === 'event') window.removeEventListener(cond.name, onCustom)
    }
  }, [active, step, location.pathname, next])

  // Успех по route / present
  useEffect(() => {
    if (!active || !step) return
    if (step.successCondition.type === 'route' && conditionMet(step.successCondition, location.pathname)) {
      const m = location.pathname.match(/^\/projects\/([^/]+)\//)
      if (m?.[1] && m[1] !== projectId) {
        setProjectId(m[1])
      }
      const t = window.setTimeout(() => next(), 120)
      return () => window.clearTimeout(t)
    }
    if (step.successCondition.type === 'present' && conditionMet(step.successCondition, location.pathname)) {
      const t = window.setTimeout(() => next(), 200)
      return () => window.clearTimeout(t)
    }
  }, [active, step, location.pathname, next, projectId])

  // Удержание в зоне через IntersectionObserver
  useEffect(() => {
    if (!active || !step || step.successCondition.type !== 'dwell') return
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
            if (dwellTimer === undefined) {
              dwellTimer = window.setTimeout(advance, minMs)
            }
          } else {
            clearDwell()
          }
        },
        { threshold: [0, minRatio, 1] },
      )
      observer.observe(el)
    }

    const el = queryTourTarget(cond.target)
    if (el) {
      attach(el)
    } else {
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
  }, [active, step, location.pathname, next, targetEpoch])

  const api: TourApi = {
    active,
    scenario,
    step,
    stepIndex,
    stepCount,
    startScenario,
    next,
    back,
    skip: next,
    finish,
    retryTarget,
  }

  const auto = step ? isAutoCondition(step.successCondition) : false
  const isDwell = step?.successCondition.type === 'dwell'
  const softMissing = Boolean(targetMissing && step?.optional)

  return (
    <TourContext.Provider value={api}>
      {children}
      {active && step && (
        <div className="tour-popover tour-coach" role="dialog" aria-label={step.title} data-tour-id="tour-coach">
          <b>
            {scenario?.title} · шаг {stepIndex + 1}/{stepCount}
          </b>
          <strong>{step.title}</strong>
          <p>{step.text}</p>
          <small className="tour-expected">Что сделать: {step.expectedAction}</small>
          {targetMissing ? (
            <p className={`tour-status${softMissing ? '' : ' is-warn'}`}>
              {step.missingHint ||
                (softMissing
                  ? 'Этот фрагмент сейчас не на экране — можно продолжить.'
                  : 'Нужный элемент ещё не появился. Подождите немного или нажмите «Повторить».')}
            </p>
          ) : isDwell ? (
            <p className="tour-status">Осмотрите экран — шаг сменится сам, либо нажмите «Далее»</p>
          ) : auto ? (
            <p className="tour-status">Сделайте это на экране…</p>
          ) : null}
          <div className="tour-actions">
            <button type="button" className="tour-btn ghost" onClick={finish}>
              Завершить
            </button>
            <button type="button" className="tour-btn ghost" onClick={back} disabled={stepIndex === 0}>
              Назад
            </button>
            {targetMissing ? (
              <>
                {!softMissing && (
                  <button type="button" className="tour-btn ghost" onClick={retryTarget}>
                    Повторить
                  </button>
                )}
                <button type="button" className="tour-btn" onClick={next}>
                  {softMissing ? 'Далее' : 'Пропустить'}
                </button>
              </>
            ) : isLast ? (
              <button type="button" className="tour-btn" onClick={finish}>
                Завершить обучение
              </button>
            ) : isDwell ? (
              <button type="button" className="tour-btn" onClick={next}>
                Далее
              </button>
            ) : auto ? (
              <button type="button" className="tour-btn" onClick={next}>
                Далее
              </button>
            ) : (
              <button type="button" className="tour-btn" onClick={next}>
                Далее
              </button>
            )}
          </div>
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

/** Опциональный hook, если provider может отсутствовать (тесты). */
export function useTourOptional() {
  return useContext(TourContext)
}
