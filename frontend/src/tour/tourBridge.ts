import { isFindingUserDismissed, markFindingUserDismissed } from './findingDismiss'
export { markFindingUserDismissed, resetFindingUserDismissed, isFindingUserDismissed } from './findingDismiss'

export type AnalyticsTourBridge = {
  ensureFiltersOpen: () => void
  setDevelopers: (developers: string[]) => void
  setOnlyDelayed: (value: boolean) => void
  setBarMetric: (metric: 'max' | 'works') => void
  snapshot: () => unknown
  restore: (snap: unknown) => void
}

export type ScheduleTourBridge = {
  focusActivity: (activityId: string) => void
  openEvidence: (activityId: string, deviationId?: number) => void
  closeEvidence?: () => void
  resetTourUi?: () => void
  setWarningsOpen: (open: boolean) => void
  setWarningsTab?: (tab: 'deviations' | 'risk' | 'all' | 'no_data') => void
}

export type CamerasTourBridge = {
  selectCamera?: (cameraId: number) => void
  selectFrame?: (frameId: number) => void
  setShowBbox?: (on: boolean) => void
  setShowRoi?: (on: boolean) => void
}

export type FindingTourBridge = {
  setTab: (tab: 'overview' | 'proofs' | 'logic' | 'comment') => void
  setFrameIndex?: (index: number) => void
  setViewMode?: (mode: 'original' | 'annotated') => void
  openZoom?: (index?: number) => void
  closeZoom?: () => void
  /** Подтвердить сигнал и запустить пересмотр прогноза КСГ. */
  confirmSignal?: () => void
}

export type ShellTourBridge = {
  openProfileMenu: () => void
  closeProfileMenu: () => void
  switchDemoUser?: (login: string) => void | Promise<void>
}

export type TourBridge = {
  analytics?: AnalyticsTourBridge | null
  schedule?: ScheduleTourBridge | null
  cameras?: CamerasTourBridge | null
  finding?: FindingTourBridge | null
  shell?: ShellTourBridge | null
  /** Связанный контекст текущего обучения (Строгино). */
  competition?: {
    developer: string
    projectId: string
    activityId: string | null
    deviationId: number | null
    cameraId: number | null
  } | null
}

const bridge: TourBridge = {}

export function getTourBridge(): TourBridge {
  return bridge
}

export function registerTourBridge(partial: Partial<TourBridge>): () => void {
  const keys = Object.keys(partial) as (keyof TourBridge)[]
  const prev: Partial<TourBridge> = {}
  for (const k of keys) {
    prev[k] = bridge[k] as never
    ;(bridge as Record<string, unknown>)[k] = partial[k]
  }
  return () => {
    for (const k of keys) {
      ;(bridge as Record<string, unknown>)[k] = prev[k]
    }
  }
}

export type TourAction =
  | { type: 'setAnalyticsDeveloper'; developer?: string }
  | { type: 'setAnalyticsOnlyDelayed'; value: boolean }
  | { type: 'setAnalyticsMetric'; metric: 'max' | 'works' }
  | { type: 'ensureAnalyticsFiltersOpen' }
  | { type: 'openProject'; projectId?: string }
  | { type: 'focusGanttActivity'; activityId?: string }
  | { type: 'openDeviation'; activityId?: string; deviationId?: number }
  | { type: 'openWarningsPanel' }
  | { type: 'closeFinding' }
  | { type: 'openFindingTab'; tab: 'overview' | 'proofs' | 'logic' | 'comment' }
  | { type: 'showEvidenceFrame'; index?: number }
  | { type: 'closeEvidenceFrame' }
  | { type: 'confirmFinding' }
  | { type: 'openProfileMenu' }
  | { type: 'closeProfileMenu' }
  | { type: 'switchDemoUser'; login: string }
  | { type: 'openSettings'; section?: 'streams' | 'upload' | 'frames' | 'api'; projectId?: string }
  | { type: 'openAdmin'; catalog?: 'work-types' | 'equipment' }
  | { type: 'goRoute'; path: string }
  | { type: 'setCameraBbox'; on: boolean }
  | { type: 'setCameraRoi'; on: boolean }
  | { type: 'wait'; ms: number }
  | { type: 'dispatchEvent'; name: string }

async function waitFor(check: () => boolean, ms: number, step = 100): Promise<boolean> {
  const end = Date.now() + ms
  while (Date.now() < end) {
    if (check()) return true
    await sleep(step)
  }
  return check()
}

export async function runTourAction(action: TourAction, navigate?: (to: string) => void): Promise<void> {
  const b = getTourBridge()
  const demo = b.competition
  switch (action.type) {
    case 'wait':
      await sleep(action.ms)
      return
    case 'dispatchEvent':
      window.dispatchEvent(new CustomEvent(action.name))
      return
    case 'ensureAnalyticsFiltersOpen':
      b.analytics?.ensureFiltersOpen()
      // Дать панели доехать (CSS), иначе spotlight «прыгает»
      await sleep(900)
      return
    case 'setAnalyticsDeveloper': {
      const dev = action.developer || demo?.developer
      if (dev) b.analytics?.setDevelopers([dev])
      await sleep(1200)
      window.dispatchEvent(new CustomEvent('plansight:tour:filters-settled'))
      await sleep(400)
      return
    }
    case 'setAnalyticsOnlyDelayed':
      b.analytics?.setOnlyDelayed(action.value)
      await sleep(1200)
      window.dispatchEvent(new CustomEvent('plansight:tour:filters-settled'))
      await sleep(400)
      return
    case 'setAnalyticsMetric':
      b.analytics?.setBarMetric(action.metric)
      await sleep(450)
      return
    case 'openProject': {
      const pid = action.projectId || demo?.projectId
      if (pid && navigate) navigate(`/projects/${pid}/schedule?warnings=1`)
      await waitFor(() => Boolean(document.querySelector('[data-tour-id="schedule-title"]')), 7000)
      await sleep(500)
      return
    }
    case 'goRoute': {
      if (navigate) navigate(action.path)
      await sleep(450)
      return
    }
    case 'focusGanttActivity': {
      await waitFor(() => Boolean(getTourBridge().schedule), 4000)
      const id = action.activityId || demo?.activityId
      if (id) getTourBridge().schedule?.focusActivity(id)
      await sleep(400)
      return
    }
    case 'openWarningsPanel':
      await waitFor(() => Boolean(getTourBridge().schedule), 4000)
      getTourBridge().schedule?.setWarningsOpen(true)
      await sleep(280)
      return
    case 'closeFinding':
      markFindingUserDismissed(true)
      getTourBridge().finding?.closeZoom?.()
      getTourBridge().schedule?.closeEvidence?.()
      await sleep(280)
      return
    case 'openDeviation': {
      if (isFindingUserDismissed()) return
      await waitFor(() => Boolean(getTourBridge().schedule), 4000)
      if (isFindingUserDismissed()) return
      const aid = action.activityId || getTourBridge().competition?.activityId
      const did = action.deviationId ?? getTourBridge().competition?.deviationId ?? undefined
      if (aid) getTourBridge().schedule?.openEvidence(aid, did ?? undefined)
      await waitFor(() => Boolean(document.querySelector('[data-tour-id="finding-card"]')), 6000)
      await sleep(450)
      return
    }
    case 'openFindingTab': {
      await waitFor(() => Boolean(getTourBridge().finding), 5000)
      getTourBridge().finding?.setTab(action.tab)
      await sleep(200)
      getTourBridge().finding?.setTab(action.tab)
      await sleep(280)
      return
    }
    case 'showEvidenceFrame':
      await waitFor(() => Boolean(getTourBridge().finding), 5000)
      getTourBridge().finding?.setFrameIndex?.(action.index ?? 0)
      getTourBridge().finding?.setViewMode?.('annotated')
      // setTab('proofs') и openZoom — открывают просмотр кадра
      getTourBridge().finding?.setTab?.('proofs')
      getTourBridge().finding?.openZoom?.(action.index ?? 0)
      await waitFor(() => Boolean(document.querySelector('[data-tour-id="frame-zoom-modal"]')), 6000)
      await sleep(500)
      return
    case 'closeEvidenceFrame':
      getTourBridge().finding?.closeZoom?.()
      getTourBridge().finding?.setTab?.('overview')
      await waitFor(() => !document.querySelector('[data-tour-id="frame-zoom-modal"]'), 2500)
      await sleep(220)
      return
    case 'confirmFinding':
      await waitFor(() => Boolean(getTourBridge().finding?.confirmSignal), 4000)
      getTourBridge().finding?.confirmSignal?.()
      await waitFor(() => Boolean(document.querySelector('[data-tour-id="schedule-impact"]')), 4000)
      await sleep(400)
      return
    case 'openProfileMenu':
      getTourBridge().shell?.openProfileMenu()
      await waitFor(() => Boolean(document.querySelector('[data-tour-id="profile-menu"]')), 2000)
      await sleep(200)
      return
    case 'closeProfileMenu':
      getTourBridge().shell?.closeProfileMenu()
      await sleep(180)
      return
    case 'switchDemoUser': {
      const fn = getTourBridge().shell?.switchDemoUser
      if (fn) await fn(action.login)
      await sleep(450)
      return
    }
    case 'openSettings': {
      const pid = action.projectId || demo?.projectId || ''
      const section = action.section || 'streams'
      const q = new URLSearchParams()
      if (pid) q.set('project', pid)
      q.set('section', section)
      const path = `/settings?${q.toString()}`
      const cur = `${window.location.pathname}${window.location.search}`
      if (navigate && cur !== path) navigate(path)
      await waitFor(() => Boolean(document.querySelector('[data-tour-id="settings-page"]')), 5000)
      await sleep(350)
      return
    }
    case 'openAdmin': {
      const catalog = action.catalog || 'equipment'
      if (navigate) navigate(`/admin/catalogs/${catalog}`)
      await waitFor(() => Boolean(document.querySelector('[data-tour-id="admin-catalogs"]')), 5000)
      await sleep(350)
      return
    }
    case 'setCameraBbox':
      await waitFor(() => Boolean(getTourBridge().cameras), 4000)
      getTourBridge().cameras?.setShowBbox?.(action.on)
      await sleep(250)
      return
    case 'setCameraRoi':
      await waitFor(() => Boolean(getTourBridge().cameras), 4000)
      getTourBridge().cameras?.setShowRoi?.(action.on)
      await sleep(250)
      return
    default:
      return
  }
}

export async function runTourActions(actions: TourAction[] | undefined, navigate?: (to: string) => void) {
  if (!actions?.length) return
  for (const a of actions) {
    await runTourAction(a, navigate)
  }
}

function sleep(ms: number) {
  return new Promise<void>((r) => window.setTimeout(r, ms))
}
