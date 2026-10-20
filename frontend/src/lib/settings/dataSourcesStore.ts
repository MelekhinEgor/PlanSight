/**
 * Клиентский реестр источников данных и настроек извлечения кадров (localStorage).
 * Stream URL и webhook'и пока не уходят на бэкенд — только UI-конфиг.
 */

export type DataSourceKind = 'stream' | 'upload_batch' | 'api_push' | 'export_webhook'

export type DataSourceStatus = 'configured' | 'paused' | 'error' | 'queued'

export type StreamProtocol = 'rtsp' | 'hls' | 'http' | 'other'

export type StreamSource = {
  id: string
  projectId: string
  kind: 'stream'
  name: string
  streamUrl: string
  protocol: StreamProtocol
  frameIntervalSec: number
  enabled: boolean
  buildingHint?: string
  backendCameraId?: number | null
  status: DataSourceStatus
  createdAt: string
  updatedAt: string
}

export type UploadQueueItem = {
  id: string
  projectId: string
  kind: 'upload_batch'
  name: string
  fileName: string
  fileType: string
  fileSize: number
  cameraName?: string
  buildingHint?: string
  videoIntervalSec?: number
  status: DataSourceStatus
  note?: string
  createdAt: string
}

export type ExportWebhookEvent = 'new_frame' | 'new_warning'

export type ExportWebhook = {
  id: string
  projectId: string
  kind: 'export_webhook'
  name: string
  url: string
  secret: string
  events: ExportWebhookEvent[]
  enabled: boolean
  status: DataSourceStatus
  createdAt: string
  updatedAt: string
}

export type ProjectFramePolicy = {
  streamIntervalSec: number
  videoIntervalSec: number
  maxFramesPerVideo: number
  preferPrintedTimestamp: boolean
  timezone: string
}

export type ProjectSettingsBundle = {
  streams: StreamSource[]
  uploads: UploadQueueItem[]
  webhooks: ExportWebhook[]
  framePolicy: ProjectFramePolicy
  apiPushEnabled: boolean
}

const STORAGE_KEY = 'plansight.settings.sources.v1'

const DEFAULT_FRAME_POLICY: ProjectFramePolicy = {
  streamIntervalSec: 300,
  videoIntervalSec: 30,
  maxFramesPerVideo: 120,
  preferPrintedTimestamp: true,
  timezone: 'Europe/Moscow',
}

type RootStore = {
  byProject: Record<string, ProjectSettingsBundle>
}

function uid(prefix: string): string {
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

function emptyBundle(): ProjectSettingsBundle {
  return {
    streams: [],
    uploads: [],
    webhooks: [],
    framePolicy: { ...DEFAULT_FRAME_POLICY },
    apiPushEnabled: true,
  }
}

function loadRoot(): RootStore {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { byProject: {} }
    const parsed = JSON.parse(raw) as RootStore
    if (!parsed || typeof parsed !== 'object' || !parsed.byProject) return { byProject: {} }
    return parsed
  } catch {
    return { byProject: {} }
  }
}

function saveRoot(root: RootStore): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(root))
  } catch {
    /* quota */
  }
}

export function getDefaultFramePolicy(): ProjectFramePolicy {
  return { ...DEFAULT_FRAME_POLICY }
}

export function loadProjectSettings(projectId: string): ProjectSettingsBundle {
  const root = loadRoot()
  const b = root.byProject[projectId]
  if (!b) return emptyBundle()
  return {
    streams: Array.isArray(b.streams) ? b.streams : [],
    uploads: Array.isArray(b.uploads) ? b.uploads : [],
    webhooks: Array.isArray(b.webhooks) ? b.webhooks : [],
    framePolicy: { ...DEFAULT_FRAME_POLICY, ...(b.framePolicy || {}) },
    apiPushEnabled: b.apiPushEnabled !== false,
  }
}

function writeProject(projectId: string, next: ProjectSettingsBundle): ProjectSettingsBundle {
  const root = loadRoot()
  root.byProject[projectId] = next
  saveRoot(root)
  return next
}

export function saveFramePolicy(projectId: string, policy: ProjectFramePolicy): ProjectSettingsBundle {
  const cur = loadProjectSettings(projectId)
  return writeProject(projectId, { ...cur, framePolicy: { ...policy } })
}

export function setApiPushEnabled(projectId: string, enabled: boolean): ProjectSettingsBundle {
  const cur = loadProjectSettings(projectId)
  return writeProject(projectId, { ...cur, apiPushEnabled: enabled })
}

export function addStreamSource(
  projectId: string,
  input: {
    name: string
    streamUrl: string
    protocol: StreamProtocol
    frameIntervalSec: number
    buildingHint?: string
    enabled?: boolean
    backendCameraId?: number | null
  },
): ProjectSettingsBundle {
  const cur = loadProjectSettings(projectId)
  const now = new Date().toISOString()
  const row: StreamSource = {
    id: uid('stream'),
    projectId,
    kind: 'stream',
    name: input.name.trim(),
    streamUrl: input.streamUrl.trim(),
    protocol: input.protocol,
    frameIntervalSec: Math.max(5, Math.floor(input.frameIntervalSec || 300)),
    enabled: input.enabled !== false,
    buildingHint: input.buildingHint?.trim() || undefined,
    backendCameraId: input.backendCameraId ?? null,
    status: input.enabled === false ? 'paused' : 'configured',
    createdAt: now,
    updatedAt: now,
  }
  return writeProject(projectId, { ...cur, streams: [row, ...cur.streams] })
}

export function updateStreamSource(
  projectId: string,
  streamId: string,
  patch: Partial<Pick<StreamSource, 'name' | 'streamUrl' | 'protocol' | 'frameIntervalSec' | 'buildingHint' | 'enabled' | 'backendCameraId' | 'status'>>,
): ProjectSettingsBundle {
  const cur = loadProjectSettings(projectId)
  const streams = cur.streams.map((s) => {
    if (s.id !== streamId) return s
    const enabled = patch.enabled ?? s.enabled
    return {
      ...s,
      ...patch,
      enabled,
      status: patch.status ?? (enabled ? 'configured' : 'paused'),
      updatedAt: new Date().toISOString(),
    }
  })
  return writeProject(projectId, { ...cur, streams })
}

export function removeStreamSource(projectId: string, streamId: string): ProjectSettingsBundle {
  const cur = loadProjectSettings(projectId)
  return writeProject(projectId, { ...cur, streams: cur.streams.filter((s) => s.id !== streamId) })
}

export function addUploadQueueItem(
  projectId: string,
  input: {
    fileName: string
    fileType: string
    fileSize: number
    cameraName?: string
    buildingHint?: string
    videoIntervalSec?: number
    status?: DataSourceStatus
    note?: string
  },
): ProjectSettingsBundle {
  const cur = loadProjectSettings(projectId)
  const row: UploadQueueItem = {
    id: uid('upload'),
    projectId,
    kind: 'upload_batch',
    name: input.fileName,
    fileName: input.fileName,
    fileType: input.fileType,
    fileSize: input.fileSize,
    cameraName: input.cameraName,
    buildingHint: input.buildingHint,
    videoIntervalSec: input.videoIntervalSec,
    status: input.status || 'queued',
    note: input.note,
    createdAt: new Date().toISOString(),
  }
  return writeProject(projectId, { ...cur, uploads: [row, ...cur.uploads].slice(0, 50) })
}

export function removeUploadQueueItem(projectId: string, uploadId: string): ProjectSettingsBundle {
  const cur = loadProjectSettings(projectId)
  return writeProject(projectId, { ...cur, uploads: cur.uploads.filter((u) => u.id !== uploadId) })
}

export function addExportWebhook(
  projectId: string,
  input: { name: string; url: string; secret: string; events: ExportWebhookEvent[]; enabled?: boolean },
): ProjectSettingsBundle {
  const cur = loadProjectSettings(projectId)
  const now = new Date().toISOString()
  const row: ExportWebhook = {
    id: uid('hook'),
    projectId,
    kind: 'export_webhook',
    name: input.name.trim() || 'Исходящий webhook',
    url: input.url.trim(),
    secret: input.secret,
    events: input.events.length ? input.events : ['new_warning'],
    enabled: input.enabled !== false,
    status: input.enabled === false ? 'paused' : 'configured',
    createdAt: now,
    updatedAt: now,
  }
  return writeProject(projectId, { ...cur, webhooks: [row, ...cur.webhooks] })
}

export function updateExportWebhook(
  projectId: string,
  hookId: string,
  patch: Partial<Pick<ExportWebhook, 'name' | 'url' | 'secret' | 'events' | 'enabled' | 'status'>>,
): ProjectSettingsBundle {
  const cur = loadProjectSettings(projectId)
  const webhooks = cur.webhooks.map((h) => {
    if (h.id !== hookId) return h
    const enabled = patch.enabled ?? h.enabled
    return {
      ...h,
      ...patch,
      enabled,
      status: patch.status ?? (enabled ? 'configured' : 'paused'),
      updatedAt: new Date().toISOString(),
    }
  })
  return writeProject(projectId, { ...cur, webhooks })
}

export function removeExportWebhook(projectId: string, hookId: string): ProjectSettingsBundle {
  const cur = loadProjectSettings(projectId)
  return writeProject(projectId, { ...cur, webhooks: cur.webhooks.filter((h) => h.id !== hookId) })
}

export type UnifiedSourceRow = {
  id: string
  kind: DataSourceKind
  name: string
  status: DataSourceStatus
  detail: string
  enabled?: boolean
}

export function listUnifiedSources(bundle: ProjectSettingsBundle): UnifiedSourceRow[] {
  const rows: UnifiedSourceRow[] = []
  for (const s of bundle.streams) {
    rows.push({
      id: s.id,
      kind: 'stream',
      name: s.name,
      status: s.status,
      detail: `${s.protocol.toUpperCase()} · кадр каждые ${s.frameIntervalSec} с`,
      enabled: s.enabled,
    })
  }
  for (const u of bundle.uploads) {
    rows.push({
      id: u.id,
      kind: 'upload_batch',
      name: u.name,
      status: u.status,
      detail: u.note || `${Math.round(u.fileSize / 1024)} КБ`,
    })
  }
  if (bundle.apiPushEnabled) {
    rows.push({
      id: 'api_push',
      kind: 'api_push',
      name: 'Приём по API (ingest)',
      status: 'configured',
      detail: 'POST /observations/ingest',
      enabled: true,
    })
  }
  for (const h of bundle.webhooks) {
    rows.push({
      id: h.id,
      kind: 'export_webhook',
      name: h.name,
      status: h.status,
      detail: h.url || 'URL не задан',
      enabled: h.enabled,
    })
  }
  return rows
}

export function kindLabelRu(kind: DataSourceKind): string {
  switch (kind) {
    case 'stream':
      return 'Поток'
    case 'upload_batch':
      return 'Загрузка'
    case 'api_push':
      return 'API'
    case 'export_webhook':
      return 'Выгрузка'
    default:
      return kind
  }
}

export function statusLabelRu(status: DataSourceStatus): string {
  switch (status) {
    case 'configured':
      return 'Настроен'
    case 'paused':
      return 'Приостановлен'
    case 'error':
      return 'Ошибка'
    case 'queued':
      return 'В очереди'
    default:
      return status
  }
}

export function protocolLabelRu(p: StreamProtocol): string {
  switch (p) {
    case 'rtsp':
      return 'RTSP'
    case 'hls':
      return 'HLS'
    case 'http':
      return 'HTTP'
    default:
      return 'Другой'
  }
}

export function detectProtocol(url: string): StreamProtocol {
  const u = url.trim().toLowerCase()
  if (u.startsWith('rtsp://')) return 'rtsp'
  if (u.includes('.m3u8') || (u.startsWith('https://') && u.includes('hls'))) return 'hls'
  if (u.startsWith('http://') || u.startsWith('https://')) return 'http'
  return 'other'
}
