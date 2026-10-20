/** Связанный контекст данных обучения (Строгино). */

import { TRAINING_DEMO_SLUG, demoDeveloperName, isStroginoProject, type DemoProjectLike } from './demoProject'

export type CompetitionDemoContext = {
  developer: string
  projectId: string
  projectSlug: string
  projectName: string
  /** id строки КСГ (schedule item) — подставляется runtime при наличии */
  activityId: string | null
  cameraId: number | null
  zoneKey: string | null
  deviationId: number | null
  frameIds: number[]
}

export function buildCompetitionDemoContext(projects: DemoProjectLike[]): CompetitionDemoContext {
  const hit = projects.find(isStroginoProject) || projects[0]
  const projectId = hit ? String(hit.id) : TRAINING_DEMO_SLUG
  const developer = demoDeveloperName(hit || { id: projectId }).trim() || 'Демо-застройщик'
  return {
    developer,
    projectId,
    projectSlug: hit?.slug || TRAINING_DEMO_SLUG,
    projectName: hit?.name || 'ЖК «Строгино 360»',
    activityId: null,
    cameraId: null,
    zoneKey: null,
    deviationId: null,
    frameIds: [],
  }
}

/** Обогащение контекста из API deviations / schedule (best-effort). */
export async function enrichCompetitionDemo(
  ctx: CompetitionDemoContext,
  api: {
    getDeviations: (pid: string) => Promise<unknown>
    getSchedule?: (pid: string) => Promise<unknown>
  },
): Promise<CompetitionDemoContext> {
  const next = { ...ctx }
  try {
    const raw = (await api.getDeviations(ctx.projectId)) as {
      items?: {
        id: number
        schedule_item_id?: string | number | null
        signal_kind?: string
        has_evidence_frames?: boolean
        lifecycle?: string
        demo_primary?: boolean
      }[]
    }
    const items = Array.isArray(raw) ? (raw as typeof raw.items) : raw?.items || []
    const open = (items || []).filter((d) => (d.lifecycle || 'OPEN').toUpperCase() !== 'RESOLVED')
    const primary =
      open.find((d) => d.demo_primary) ||
      open.find((d) => d.signal_kind === 'CV_VERIFIED_FINDING' || d.has_evidence_frames) ||
      open[0]
    if (primary) {
      next.deviationId = primary.id
      if (primary.schedule_item_id != null) next.activityId = String(primary.schedule_item_id)
    }
  } catch {
    /* leave nulls */
  }

  if (api.getSchedule && !next.activityId) {
    try {
      const sch = (await api.getSchedule(ctx.projectId)) as {
        activities?: { id: string; name?: string; actual_progress?: number }[]
      }
      const acts = sch.activities || []
      const pick =
        acts.find((a) => /землян|котлован|вывоз|монолит/i.test(a.name || '')) ||
        acts.find((a) => (a.actual_progress ?? 0) < 100) ||
        acts[0]
      if (pick) next.activityId = pick.id
    } catch {
      /* ignore */
    }
  }
  return next
}

export const COMPETITION_STORAGE_KEY = 'plansight.tour.competition.v5'
