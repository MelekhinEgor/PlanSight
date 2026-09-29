/**
 * HTTP-мост V4.2 Stage 3+ для имён методов api PlanSight(3).
 * Активен при VITE_DEMO_MODE !== 'true' (по умолчанию backend — source of truth).
 */

const API_BASE = ''

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    const body = init?.body
    const isForm = typeof FormData !== 'undefined' && body instanceof FormData
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        ...(isForm ? {} : { 'Content-Type': 'application/json' }),
        ...(init?.headers || {}),
      },
    })
  } catch {
    throw new ApiError(0, 'Нет соединения с API. Запустите backend на порту 8010.')
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    let detail = text
    try {
      const j = JSON.parse(text)
      detail = typeof j.detail === 'string' ? j.detail : text
    } catch {
      /* оставить */
    }
    throw new ApiError(res.status, detail || `Ошибка API ${res.status}`)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

let ctxProjectId: string | null = null

export function setRemoteProjectId(projectId: string | null) {
  ctxProjectId = projectId
}

function requireProjectId(): string {
  if (!ctxProjectId) throw new ApiError(400, 'Не выбран проект для API')
  return ctxProjectId
}

function mapProject(raw: Record<string, unknown>) {
  const devRaw = raw.developer
  let developer: { id: string; name: string; groupId: string | null } | null = null
  if (typeof devRaw === 'string' && devRaw) {
    developer = { id: 'org', name: devRaw, groupId: (raw.companyGroupId as string) || null }
  } else if (devRaw && typeof devRaw === 'object') {
    const d = devRaw as { id?: string; name?: string; groupId?: string | null }
    developer = { id: String(d.id || 'org'), name: String(d.name || '—'), groupId: d.groupId ?? null }
  }
  return {
    id: String(raw.id),
    name: String(raw.name || ''),
    address: (raw.address as string) ?? null,
    region: (raw.region as string) ?? null,
    status: String(raw.status || 'NO_DATA'),
    timezone: String(raw.timezone || 'Europe/Moscow'),
    developer,
    imageUrl: (raw.imageUrl as string) ?? (raw.image_url as string) ?? null,
    commissioning: (raw.commissioning as string) ?? null,
    metro: (raw.metro as string) ?? null,
    metroWalk: (raw.metroWalk as string) ?? null,
    is_demo: Boolean(raw.is_demo),
    badge_schedule: (raw.badge_schedule as string) ?? null,
    badge_photos: (raw.badge_photos as string) ?? null,
    as_of: (raw.as_of as string) ?? null,
    data_origin: (raw.data_origin as string) ?? null,
  }
}

export const remote = {
  async getProjects() {
    const rows = await http<Record<string, unknown>[]>('/api/projects')
    return rows.map(mapProject)
  },

  async getProject(projectId: string) {
    setRemoteProjectId(projectId)
    return mapProject(await http(`/api/projects/${projectId}`))
  },

  async getProjectObjects(projectId: string) {
    const raw = await http<{ items?: unknown[] } | unknown[]>(`/api/projects/${projectId}/objects`)
    const list = Array.isArray(raw) ? raw : raw.items || []
    return list.map((row) => {
      const o = row as Record<string, unknown>
      return {
        id: String(o.id),
        project_id: String(o.project_id ?? projectId),
        parent_id: o.parent_id == null || o.parent_id === '' ? null : String(o.parent_id),
        name: String(o.name || ''),
        object_type: String(o.object_type || o.type || 'building'),
      }
    })
  },

  async getPortfolio() {
    return http('/api/portfolio')
  },

  async getSchedule(projectId: string, version?: number, objectId?: string | null) {
    setRemoteProjectId(projectId)
    const qs = new URLSearchParams()
    if (version != null) qs.set('version', String(version))
    if (objectId) qs.set('object_id', objectId)
    const q = qs.toString() ? `?${qs}` : ''
    const ws = await http<Record<string, unknown>>(`/api/projects/${projectId}/schedules/workspace${q}`)
    return {
      ...ws,
      network_recovery: ws.network_recovery ?? null,
    }
  },

  async getVersions(projectId: string) {
    const raw = await http<{ items: unknown[] }>(`/api/projects/${projectId}/schedules/versions`)
    return raw.items || []
  },

  async createWorkingCopy(projectId: string, sourceVersionId?: string | null) {
    if (sourceVersionId) {
      return http(`/api/projects/${projectId}/schedules/${sourceVersionId}/fork`, { method: 'POST', body: '{}' })
    }
    return http(`/api/projects/${projectId}/schedules/fork`, { method: 'POST', body: '{}' })
  },

  async saveScheduleEdits(
    projectId: string,
    body: { version_id: string; activities: unknown[]; dependencies: unknown[]; recalculate: boolean },
  ) {
    return http(`/api/projects/${projectId}/schedules/${body.version_id}`, {
      method: 'PATCH',
      body: JSON.stringify({
        activities: body.activities,
        dependencies: body.dependencies,
        recalculate: body.recalculate,
      }),
    })
  },

  async publishSchedule(projectId: string, versionId: string) {
    return http(`/api/projects/${projectId}/schedules/${versionId}/publish`, { method: 'POST', body: '{}' })
  },

  async exportSchedule(projectId: string, format: 'xlsx' | 'csv', version?: number) {
    const q = new URLSearchParams({ format })
    if (version != null) q.set('version', String(version))
    const res = await fetch(`/api/projects/${projectId}/schedules/export?${q}`)
    if (!res.ok) throw new ApiError(res.status, await res.text())
    const blob = await res.blob()
    const cd = res.headers.get('content-disposition') || ''
    const m = cd.match(/filename="?([^";]+)"?/)
    return { blob, filename: m?.[1] || `schedule.${format}` }
  },

  async importSchedule(projectId: string, file: File, overrides?: unknown[]) {
    const fd = new FormData()
    fd.append('file', file)
    if (overrides?.length) fd.append('overrides', JSON.stringify(overrides))
    const meta = await http<Record<string, unknown>>(`/api/projects/${projectId}/schedule`, {
      method: 'POST',
      body: fd,
      headers: {},
    })
    return { ...meta, network_recovery: meta.network_recovery ?? null }
  },

  async previewImport(projectId: string, file: File) {
    const fd = new FormData()
    fd.append('file', file)
    return http(`/api/projects/${projectId}/schedule/preview`, {
      method: 'POST',
      body: fd,
      headers: {},
    })
  },

  async getEvidenceThread(activityId: string, signal: 'DEVIATION' | 'RISK' = 'RISK') {
    const pid = requireProjectId()
    const raw = await http<{ items?: unknown[] }>(
      `/api/projects/${pid}/activities/${encodeURIComponent(activityId)}/evidence-thread?signal=${signal}`,
    )
    return raw.items || []
  },

  async addEvidenceComment(activityId: string, text: string, signal: 'DEVIATION' | 'RISK' = 'RISK') {
    const pid = requireProjectId()
    const raw = await http<{ items?: unknown[] }>(
      `/api/projects/${pid}/activities/${encodeURIComponent(activityId)}/evidence-thread?signal=${signal}`,
      {
        method: 'POST',
        body: JSON.stringify({ text, kind: 'user', author: 'Оператор', role: 'PM', initials: 'ОП' }),
      },
    )
    return raw.items || []
  },

  async getEvidenceComment(activityId: string) {
    const thread = (await remote.getEvidenceThread(activityId, 'RISK')) as { kind?: string; text?: string }[]
    return thread.filter((c) => c.kind === 'user').at(-1)?.text ?? ''
  },

  async saveEvidenceComment(activityId: string, text: string) {
    const thread = (await remote.addEvidenceComment(activityId, text)) as { kind?: string; text?: string }[]
    return thread.filter((c) => c.kind === 'user').at(-1)?.text ?? ''
  },

  async getCameras(projectId: string) {
    try {
      const rows = await http<unknown[]>(`/api/projects/${projectId}/cameras`)
      if (Array.isArray(rows)) return rows
    } catch {
      /* запасной вариант ниже */
    }
    const p = await http<{ cameras?: unknown[] }>(`/api/projects/${projectId}`)
    return p.cameras || []
  },

  async getZones(projectId: string, cameraId: number) {
    return http(`/api/projects/${projectId}/cameras/${cameraId}/zones`)
  },

  async verifyZone(projectId: string, zoneId: number, building: string) {
    return http(`/api/projects/${projectId}/zones/${zoneId}/verify`, {
      method: 'POST',
      body: JSON.stringify({ building }),
    })
  },

  async demoZonesK1K2(projectId: string, cameraId: number) {
    return http(`/api/projects/${projectId}/cameras/${cameraId}/zones/demo-k1-k2`, {
      method: 'POST',
      body: JSON.stringify({}),
    })
  },

  async getFrames(projectId: string, cameraId?: number) {
    const q = cameraId != null ? `?camera_id=${cameraId}&limit=30` : '?limit=30'
    return http(`/api/projects/${projectId}/frames${q}`)
  },

  async getFrameDetections(frameId: number) {
    return http<{ detections?: unknown[] }>(`/api/frames/${frameId}/detections`)
  },

  async getDeviations(projectId: string) {
    const raw = await http<{
      items?: unknown[]
      buckets?: { attention?: unknown[]; needs_data?: unknown[]; other?: unknown[] }
      counts?: { attention?: number; needs_data?: number; other?: number }
    } | unknown[]>(`/api/projects/${projectId}/deviations`)
    if (Array.isArray(raw)) return { items: raw }
    return {
      items: raw.items || [],
      buckets: raw.buckets,
      counts: raw.counts,
    }
  },

  async getDeviationEvidence(projectId: string, deviationId: string | number) {
    return http(`/api/projects/${projectId}/deviations/${deviationId}/evidence`)
  },

  async getDecisionTrace(projectId: string, deviationId: string | number) {
    return http(`/api/projects/${projectId}/deviations/${deviationId}/decision-trace`)
  },

  async patchDeviation(
    projectId: string,
    deviationId: string | number,
    payload: { lifecycle?: string; status?: string; note?: string },
  ) {
    return http(`/api/projects/${projectId}/deviations/${deviationId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },

  async submitDeviationVerdict(
    projectId: string,
    deviationId: string | number,
    payload: { verdict: string; correction?: Record<string, unknown>; user_id?: string },
  ) {
    return http(`/api/projects/${projectId}/deviations/${deviationId}/verdict`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async getJob(jobId: string) {
    return http(`/api/ops/jobs/${jobId}`)
  },

  async vlmAssist(payload: Record<string, unknown>) {
    return http('/api/ai/vlm-assist', { method: 'POST', body: JSON.stringify(payload) })
  },

  async aiStatus() {
    return http('/api/ai/status')
  },

  async createCamera(
    projectId: string,
    payload: { name: string; building_hint?: string | null; expected_interval_sec?: number },
  ) {
    return http(`/api/projects/${projectId}/cameras`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async ingestObservations(
    projectId: string,
    opts: {
      file: File
      cameraId?: number
      cameraName?: string
      buildingHint?: string
      capturedAt: string
      timezone?: string
      videoIntervalSec?: number
      process?: boolean
    },
  ) {
    const fd = new FormData()
    fd.append('file', opts.file)
    fd.append('captured_at', opts.capturedAt)
    fd.append('timezone', opts.timezone || 'Europe/Moscow')
    fd.append('process', String(opts.process !== false))
    fd.append('run_deviations', 'true')
    if (opts.cameraId != null) fd.append('camera_id', String(opts.cameraId))
    if (opts.cameraName) fd.append('camera_name', opts.cameraName)
    if (opts.buildingHint) fd.append('building_hint', opts.buildingHint)
    if (opts.videoIntervalSec != null) fd.append('video_interval_sec', String(opts.videoIntervalSec))
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/observations/ingest`, {
      method: 'POST',
      body: fd,
    })
    const text = await res.text()
    let body: unknown = null
    try {
      body = text ? JSON.parse(text) : null
    } catch {
      body = { raw: text }
    }
    if (!res.ok && res.status !== 202) {
      const msg =
        typeof body === 'object' && body && 'detail' in body
          ? String((body as { detail: unknown }).detail)
          : text || res.statusText
      throw new Error(msg)
    }
    const parsed = (body || {}) as {
      job_id?: string
      status?: string
      progress_url?: string
      mode?: string
      frame_count?: number
      deviations_touched?: number
      camera_name?: string
    }
    // Асинхронный ZIP/video: опрос до COMPLETED
    if (res.status === 202 && parsed.job_id) {
      const jobId = parsed.job_id
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 500))
        const job = (await this.getJob(jobId)) as {
          status?: string
          error?: string
          result?: {
            frame_count?: number
            deviations_touched?: number
            camera_name?: string
            progress?: Record<string, boolean>
          }
        }
        if (job.status === 'FAILED') throw new Error(job.error || 'Анализ не удалось выполнить')
        if (job.status === 'COMPLETED') {
          return {
            ...(job.result || {}),
            job_id: jobId,
            mode: 'async',
            status: job.status,
            stages_done: job.result?.progress,
          }
        }
      }
      throw new Error('Таймаут ожидания анализа')
    }
    return parsed
  },

  async getScheduleItemEvidence(projectId: string, itemId: string, asOf?: string | null) {
    const q = asOf ? `?as_of=${encodeURIComponent(asOf)}` : ''
    return http(`/api/projects/${projectId}/schedule-items/${encodeURIComponent(itemId)}/evidence${q}`)
  },

  async getOverview(projectId: string) {
    return http(`/api/projects/${projectId}/overview`)
  },

  async getCatalog(catalogKey: string) {
    return http(`/api/admin/catalogs/${catalogKey}`)
  },

  async putCatalog(catalogKey: string, payload: unknown) {
    return http(`/api/admin/catalogs/${catalogKey}`, { method: 'PUT', body: JSON.stringify(payload) })
  },

  async getWorkProfiles() {
    return http('/api/admin/work-profiles')
  },

  async putWorkProfiles(payload: unknown) {
    return http('/api/admin/work-profiles', { method: 'PUT', body: JSON.stringify(payload) })
  },

  async mappingStatus() {
    return http('/api/ai/mapping/status', { method: 'POST', body: '{}' })
  },

  async updateNetworkRecovery(projectId: string, versionId: string, patch: unknown) {
    const res = await http(`/api/projects/${projectId}/schedules/${versionId}/network-recovery`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }) as { network_recovery?: unknown }
    return res.network_recovery ?? patch
  },
}

export function useHttpBackend(): boolean {
  return import.meta.env.VITE_DEMO_MODE !== 'true'
}
