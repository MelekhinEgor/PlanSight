import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import { useHttpBackend } from '../api/remoteBackend'
import { useAuth } from '../auth/AuthContext'
import { appRoleLabel, appRoleOf, canManageDataSources } from '../auth/roles'
import {
  addExportWebhook,
  addStreamSource,
  addUploadQueueItem,
  detectProtocol,
  getDefaultFramePolicy,
  loadProjectSettings,
  protocolLabelRu,
  removeExportWebhook,
  removeStreamSource,
  removeUploadQueueItem,
  saveFramePolicy,
  statusLabelRu,
  updateExportWebhook,
  updateStreamSource,
  type DataSourceStatus,
  type ExportWebhookEvent,
  type ProjectFramePolicy,
  type ProjectSettingsBundle,
  type StreamProtocol,
} from '../lib/settings/dataSourcesStore'

type SectionId = 'streams' | 'upload' | 'frames' | 'api'

const NAV: { id: SectionId; name: string }[] = [
  { id: 'streams', name: 'Камеры' },
  { id: 'upload', name: 'Файлы' },
  { id: 'frames', name: 'Кадры' },
  { id: 'api', name: 'API' },
]

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} Б`
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} КБ`
  return `${(n / (1024 * 1024)).toFixed(1)} МБ`
}

function defaultCaptureLocal(): string {
  const d = new Date()
  const pad = (x: number) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function statusTone(status: DataSourceStatus): string {
  if (status === 'configured') return 'is-ok'
  if (status === 'paused') return 'is-muted'
  if (status === 'error') return 'is-bad'
  return 'is-warn'
}

function StatusPill({ status }: { status: DataSourceStatus }) {
  return <span className={`settings-pill ${statusTone(status)}`}>{statusLabelRu(status)}</span>
}

function Panel({
  title,
  lead,
  children,
  foot,
}: {
  title: string
  lead?: string
  children?: ReactNode
  foot?: ReactNode
}) {
  return (
    <div className="admin-panel settings-panel">
      <div className="admin-panel-head">
        <h2>{title}</h2>
        {lead ? <p>{lead}</p> : null}
      </div>
      {children}
      {foot ? <div className="admin-panel-foot">{foot}</div> : null}
    </div>
  )
}

export function SettingsPage() {
  const navigate = useNavigate()
  const auth = useAuth()
  const canManage = canManageDataSources(auth.user)
  const roleName = appRoleLabel(appRoleOf(auth.user))
  const [params, setParams] = useSearchParams()
  const httpOn = useHttpBackend()
  const projects = useQuery({ queryKey: ['projects'], queryFn: api.getProjects })

  const projectId = params.get('project') || projects.data?.[0]?.id || ''
  const sectionParam = params.get('section')
  const section: SectionId = NAV.some((i) => i.id === sectionParam)
    ? (sectionParam as SectionId)
    : 'streams'

  const setProjectId = (id: string) => {
    const next = new URLSearchParams(params)
    next.set('project', id)
    setParams(next, { replace: true })
  }

  const setSection = (id: SectionId) => {
    const next = new URLSearchParams(params)
    next.set('section', id)
    if (projectId) next.set('project', projectId)
    setParams(next, { replace: true })
  }

  useEffect(() => {
    if (!projectId && projects.data?.[0]?.id) setProjectId(projects.data[0].id)
  }, [projectId, projects.data])

  const [bundle, setBundle] = useState<ProjectSettingsBundle>(() =>
    projectId ? loadProjectSettings(projectId) : loadProjectSettings(''),
  )
  const [flash, setFlash] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const reload = useCallback((pid: string) => setBundle(loadProjectSettings(pid)), [])
  useEffect(() => {
    if (projectId) reload(projectId)
  }, [projectId, reload])

  const [streamName, setStreamName] = useState('')
  const [streamUrl, setStreamUrl] = useState('')
  const [streamProtocol, setStreamProtocol] = useState<StreamProtocol>('rtsp')
  const [streamHint, setStreamHint] = useState('')
  const [streamInterval, setStreamInterval] = useState(300)
  const [streamEnabled, setStreamEnabled] = useState(true)

  useEffect(() => {
    setStreamInterval(bundle.framePolicy.streamIntervalSec || 300)
  }, [bundle.framePolicy.streamIntervalSec, projectId])

  useEffect(() => {
    if (streamUrl) setStreamProtocol(detectProtocol(streamUrl))
  }, [streamUrl])

  const [uploadCamera, setUploadCamera] = useState('Камера наблюдения')
  const [uploadHint, setUploadHint] = useState('')
  const [uploadVideoInterval, setUploadVideoInterval] = useState(30)

  useEffect(() => {
    setUploadVideoInterval(bundle.framePolicy.videoIntervalSec || 30)
  }, [bundle.framePolicy.videoIntervalSec, projectId])

  const [policyDraft, setPolicyDraft] = useState<ProjectFramePolicy>(getDefaultFramePolicy())
  useEffect(() => {
    setPolicyDraft({ ...bundle.framePolicy })
  }, [bundle.framePolicy, projectId])

  const [hookName, setHookName] = useState('Webhook')
  const [hookUrl, setHookUrl] = useState('')
  const [hookSecret, setHookSecret] = useState('')
  const [hookEvents, setHookEvents] = useState<ExportWebhookEvent[]>(['new_warning'])

  const notify = (msg: string) => {
    setFlash(msg)
    setError(null)
    window.setTimeout(() => setFlash(null), 3500)
  }

  const denyUnlessTech = () => {
    if (canManage) return false
    setError('Недостаточно прав для изменения источников данных')
    return true
  }

  const onAddStream = async () => {
    if (!projectId || denyUnlessTech()) return
    if (!streamName.trim() || !streamUrl.trim()) {
      setError('Нужны название и URL')
      return
    }
    setBusy(true)
    setError(null)
    try {
      let backendCameraId: number | null = null
      if (httpOn) {
        const created = (await api.createCamera(projectId, {
          name: streamName.trim(),
          building_hint: streamHint.trim() || null,
          expected_interval_sec: streamInterval,
        })) as { id?: number }
        backendCameraId = typeof created?.id === 'number' && created.id > 0 ? created.id : null
      }
      setBundle(
        addStreamSource(projectId, {
          name: streamName.trim(),
          streamUrl: streamUrl.trim(),
          protocol: streamProtocol,
          frameIntervalSec: streamInterval,
          buildingHint: streamHint.trim() || undefined,
          enabled: streamEnabled,
          backendCameraId,
        }),
      )
      setStreamName('')
      setStreamUrl('')
      setStreamHint('')
      notify(backendCameraId ? 'Камера добавлена' : 'Поток сохранён')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ошибка сохранения')
    } finally {
      setBusy(false)
    }
  }

  const onFiles = async (files: FileList | null) => {
    if (!projectId || !files?.length || denyUnlessTech()) return
    setBusy(true)
    setError(null)
    try {
      for (const file of Array.from(files)) {
        const isVideo = /^video\//i.test(file.type) || /\.(mp4|mov|mkv|webm)$/i.test(file.name)
        if (httpOn) {
          try {
            await api.ingestObservations(projectId, {
              file,
              cameraName: uploadCamera.trim() || 'Камера наблюдения',
              buildingHint: uploadHint.trim() || undefined,
              capturedAt: defaultCaptureLocal(),
              timezone: bundle.framePolicy.timezone || 'Europe/Moscow',
              videoIntervalSec: isVideo ? uploadVideoInterval : undefined,
            })
            setBundle(
              addUploadQueueItem(projectId, {
                fileName: file.name,
                fileType: file.type || (isVideo ? 'video' : 'image'),
                fileSize: file.size,
                cameraName: uploadCamera,
                buildingHint: uploadHint || undefined,
                videoIntervalSec: isVideo ? uploadVideoInterval : undefined,
                status: 'configured',
                note: isVideo ? `Нарезка ${uploadVideoInterval} с` : 'Кадр',
              }),
            )
          } catch (e) {
            setBundle(
              addUploadQueueItem(projectId, {
                fileName: file.name,
                fileType: file.type,
                fileSize: file.size,
                status: 'error',
                note: e instanceof Error ? e.message : 'Ошибка',
              }),
            )
          }
        } else {
          setBundle(
            addUploadQueueItem(projectId, {
              fileName: file.name,
              fileType: file.type || (isVideo ? 'video' : 'image'),
              fileSize: file.size,
              cameraName: uploadCamera,
              buildingHint: uploadHint || undefined,
              videoIntervalSec: isVideo ? uploadVideoInterval : undefined,
              status: 'queued',
              note: 'Ожидает HTTP-бэкенд',
            }),
          )
        }
      }
      notify(httpOn ? 'Загружено' : 'В очереди')
    } finally {
      setBusy(false)
    }
  }

  const onSavePolicy = () => {
    if (!projectId || denyUnlessTech()) return
    setBundle(
      saveFramePolicy(projectId, {
        ...policyDraft,
        streamIntervalSec: Math.max(5, Math.floor(policyDraft.streamIntervalSec || 300)),
        videoIntervalSec: Math.max(1, Math.floor(policyDraft.videoIntervalSec || 30)),
        maxFramesPerVideo: Math.max(1, Math.floor(policyDraft.maxFramesPerVideo || 120)),
      }),
    )
    notify('Сохранено')
  }

  const onAddWebhook = () => {
    if (!projectId || denyUnlessTech()) return
    if (!hookUrl.trim()) {
      setError('Укажите URL')
      return
    }
    setBundle(
      addExportWebhook(projectId, {
        name: hookName,
        url: hookUrl,
        secret: hookSecret,
        events: hookEvents,
        enabled: true,
      }),
    )
    setHookUrl('')
    setHookSecret('')
    notify('Webhook сохранён')
  }

  return (
    <div className="admin-page settings-page" data-tour-id="settings-page">
      <div className="admin-head settings-head">
        <button type="button" className="admin-back" onClick={() => navigate(-1)} aria-label="Назад">
          ←
        </button>
        <div className="settings-head-main">
          <h1>Настройки</h1>
          <p>Источники данных проекта</p>
        </div>
        <div className="settings-head-project">
          <label className="settings-field">
            <span>Проект</span>
            <select
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              disabled={!projects.data?.length}
              data-tour-id="settings-project"
            >
              {!projects.data?.length && <option value="">Нет проектов</option>}
              {(projects.data || []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <span className={`settings-mode-chip${httpOn ? ' is-http' : ''}`}>
            {httpOn ? 'HTTP' : 'Локально'}
          </span>
        </div>
      </div>

      {!canManage && (
        <aside className="settings-role-plaque" data-tour-id="settings-role-gate" aria-label="Права доступа">
          <span className="settings-role-plaque-mark" aria-hidden />
          <div className="settings-role-plaque-body">
            <b>Источники данных</b>
            <p>
              Подключение и удаление камер, файлов и API выполняет технический специалист. Ваша роль —{' '}
              {roleName.toLowerCase()}: конфигурацию можно просмотреть.
            </p>
          </div>
        </aside>
      )}

      {(flash || error) && (
        <div className={`settings-toast${error ? ' is-error' : ''}`} role="status">
          {error || flash}
        </div>
      )}

      <div
        className={`admin-layout settings-layout${canManage ? '' : ' is-readonly'}`}
        data-tour-id="settings-layout"
        data-can-manage={canManage ? '1' : '0'}
      >
        <aside className="admin-nav settings-nav" aria-label="Разделы">
          <nav className="admin-nav-list">
            {NAV.map((item) => (
              <button
                key={item.id}
                type="button"
                className={section === item.id ? 'admin-nav-item active' : 'admin-nav-item'}
                onClick={() => setSection(item.id)}
                data-tour-id={`settings-nav-${item.id}`}
              >
                {item.name}
                {item.id === 'streams' && bundle.streams.length > 0 ? (
                  <em className="settings-nav-count">{bundle.streams.length}</em>
                ) : null}
                {item.id === 'upload' && bundle.uploads.length > 0 ? (
                  <em className="settings-nav-count">{bundle.uploads.length}</em>
                ) : null}
              </button>
            ))}
          </nav>
        </aside>

        <div className="admin-body settings-body">
          {!projectId ? (
            <Panel title="Нет проекта" lead="Добавьте проект в системе" />
          ) : section === 'streams' ? (
            <>
              <Panel title="Подключить камеру">
                <div className="settings-form" data-tour-id="settings-stream-form">
                  <div className="settings-form-row">
                    <label className="settings-field settings-field-grow">
                      <span>Название</span>
                      <input
                        value={streamName}
                        onChange={(e) => setStreamName(e.target.value)}
                        placeholder="Корпус 1.3 · котлован"
                        data-tour-id="settings-stream-name"
                      />
                    </label>
                    <label className="settings-field">
                      <span>Зона</span>
                      <input
                        value={streamHint}
                        onChange={(e) => setStreamHint(e.target.value)}
                        placeholder="1.3"
                      />
                    </label>
                  </div>
                  <label className="settings-field">
                    <span>URL потока</span>
                    <input
                      value={streamUrl}
                      onChange={(e) => setStreamUrl(e.target.value)}
                      placeholder="rtsp://host:554/stream"
                      data-tour-id="settings-stream-url"
                    />
                  </label>
                  <div className="settings-form-row">
                    <label className="settings-field">
                      <span>Протокол</span>
                      <select
                        value={streamProtocol}
                        onChange={(e) => setStreamProtocol(e.target.value as StreamProtocol)}
                      >
                        <option value="rtsp">RTSP</option>
                        <option value="hls">HLS</option>
                        <option value="http">HTTP</option>
                        <option value="other">Другой</option>
                      </select>
                    </label>
                    <label className="settings-field">
                      <span>Кадр каждые, сек</span>
                      <input
                        type="number"
                        min={5}
                        step={5}
                        value={streamInterval}
                        onChange={(e) => setStreamInterval(Number(e.target.value) || 300)}
                      />
                    </label>
                    <label className="settings-field settings-field-check">
                      <span>&nbsp;</span>
                      <label className="settings-check">
                        <input
                          type="checkbox"
                          checked={streamEnabled}
                          onChange={(e) => setStreamEnabled(e.target.checked)}
                        />
                        <span>Активна</span>
                      </label>
                    </label>
                  </div>
                  <div className="settings-form-actions">
                    <button
                      type="button"
                      className="admin-btn primary"
                      disabled={busy || !canManage}
                      onClick={() => void onAddStream()}
                      data-tour-id="settings-stream-submit"
                    >
                      Добавить
                    </button>
                  </div>
                </div>
              </Panel>

              <Panel title="Список" lead={bundle.streams.length ? undefined : 'Пока пусто'}>
                {bundle.streams.length > 0 && (
                  <div className="admin-table-wrap">
                    <table className="admin-table">
                      <thead>
                        <tr>
                          <th>Камера</th>
                          <th>Протокол</th>
                          <th>URL</th>
                          <th>Интервал</th>
                          <th>Статус</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {bundle.streams.map((s) => (
                          <tr key={s.id}>
                            <td>
                              <b className="settings-row-title">{s.name}</b>
                              {s.buildingHint ? (
                                <small className="settings-muted-block">{s.buildingHint}</small>
                              ) : null}
                              {s.backendCameraId ? (
                                <small className="settings-muted-block">id {s.backendCameraId}</small>
                              ) : null}
                            </td>
                            <td>{protocolLabelRu(s.protocol)}</td>
                            <td className="settings-url-cell" title={s.streamUrl}>
                              {s.streamUrl}
                            </td>
                            <td>{s.frameIntervalSec} с</td>
                            <td>
                              <StatusPill status={s.status} />
                            </td>
                            <td className="settings-actions">
                              <button
                                type="button"
                                className="admin-btn"
                                disabled={!canManage}
                                onClick={() => {
                                  if (denyUnlessTech()) return
                                  setBundle(updateStreamSource(projectId, s.id, { enabled: !s.enabled }))
                                }}
                              >
                                {s.enabled ? 'Пауза' : 'Вкл'}
                              </button>
                              <button
                                type="button"
                                className="admin-btn danger"
                                disabled={!canManage}
                                data-tour-id="settings-stream-delete"
                                onClick={() => {
                                  if (denyUnlessTech()) return
                                  setBundle(removeStreamSource(projectId, s.id))
                                  notify('Удалено')
                                }}
                              >
                                Удалить
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Panel>
            </>
          ) : section === 'upload' ? (
            <>
              <Panel title="Загрузка" lead="Фото — кадр целиком. Видео режется по интервалу.">
                <div className="settings-form">
                  <div className="settings-form-row">
                    <label className="settings-field">
                      <span>Источник</span>
                      <input value={uploadCamera} onChange={(e) => setUploadCamera(e.target.value)} />
                    </label>
                    <label className="settings-field">
                      <span>Зона</span>
                      <input value={uploadHint} onChange={(e) => setUploadHint(e.target.value)} />
                    </label>
                    <label className="settings-field">
                      <span>Нарезка видео, сек</span>
                      <input
                        type="number"
                        min={1}
                        value={uploadVideoInterval}
                        onChange={(e) => setUploadVideoInterval(Number(e.target.value) || 30)}
                      />
                    </label>
                  </div>
                  <label className={`settings-dropzone${busy || !canManage ? ' is-busy' : ''}`} data-tour-id="settings-upload-drop">
                    <input
                      type="file"
                      multiple
                      accept="image/*,video/*,.jpg,.jpeg,.png,.webp,.mp4,.mov,.mkv,.webm,.zip"
                      disabled={busy || !canManage}
                      onChange={(e) => {
                        void onFiles(e.target.files)
                        e.target.value = ''
                      }}
                    />
                    <strong>{busy ? 'Загрузка…' : 'Выбрать файлы'}</strong>
                    <span>jpg, png, mp4, zip</span>
                  </label>
                </div>
              </Panel>

              <Panel title="Журнал" lead={bundle.uploads.length ? undefined : 'Пусто'}>
                {bundle.uploads.length > 0 && (
                  <div className="admin-table-wrap">
                    <table className="admin-table">
                      <thead>
                        <tr>
                          <th>Файл</th>
                          <th>Размер</th>
                          <th>Статус</th>
                          <th>Примечание</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {bundle.uploads.map((u) => (
                          <tr key={u.id}>
                            <td>
                              <b className="settings-row-title">{u.fileName}</b>
                            </td>
                            <td>{fmtBytes(u.fileSize)}</td>
                            <td>
                              <StatusPill status={u.status} />
                            </td>
                            <td className="settings-detail-cell">{u.note || '—'}</td>
                            <td>
                              <button
                                type="button"
                                className="admin-btn danger"
                                disabled={!canManage}
                                onClick={() => {
                                  if (denyUnlessTech()) return
                                  setBundle(removeUploadQueueItem(projectId, u.id))
                                }}
                              >
                                Удалить
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Panel>
            </>
          ) : section === 'frames' ? (
            <Panel
              title="Извлечение кадров"
              lead="Дефолты для новых потоков и видео"
              foot={
                <button type="button" className="admin-btn primary" disabled={!canManage} onClick={onSavePolicy}>
                  Сохранить
                </button>
              }
            >
              <div className="settings-form" data-tour-id="settings-frames-form">
                <div className="settings-form-row">
                  <label className="settings-field">
                    <span>Поток, сек</span>
                    <input
                      type="number"
                      min={5}
                      value={policyDraft.streamIntervalSec}
                      onChange={(e) =>
                        setPolicyDraft((p) => ({ ...p, streamIntervalSec: Number(e.target.value) || 300 }))
                      }
                    />
                  </label>
                  <label className="settings-field">
                    <span>Видеофайл, сек</span>
                    <input
                      type="number"
                      min={1}
                      value={policyDraft.videoIntervalSec}
                      onChange={(e) =>
                        setPolicyDraft((p) => ({ ...p, videoIntervalSec: Number(e.target.value) || 30 }))
                      }
                    />
                  </label>
                  <label className="settings-field">
                    <span>Макс. кадров / ролик</span>
                    <input
                      type="number"
                      min={1}
                      value={policyDraft.maxFramesPerVideo}
                      onChange={(e) =>
                        setPolicyDraft((p) => ({ ...p, maxFramesPerVideo: Number(e.target.value) || 120 }))
                      }
                    />
                  </label>
                </div>
                <label className="settings-field">
                  <span>Часовой пояс</span>
                  <input
                    value={policyDraft.timezone}
                    onChange={(e) => setPolicyDraft((p) => ({ ...p, timezone: e.target.value }))}
                    placeholder="Europe/Moscow"
                  />
                </label>
                <label className="settings-check">
                  <input
                    type="checkbox"
                    checked={policyDraft.preferPrintedTimestamp}
                    onChange={(e) =>
                      setPolicyDraft((p) => ({ ...p, preferPrintedTimestamp: e.target.checked }))
                    }
                  />
                  <span>Не смешивать дату на кадре с временем захвата</span>
                </label>
              </div>
            </Panel>
          ) : (
            <>
              <Panel title="Ingest" lead={`POST /api/projects/${projectId}/observations/ingest`}>
                <div className="settings-form" data-tour-id="settings-api-panel">
                  <pre className="settings-code">{`curl -X POST "$API/api/projects/${projectId}/observations/ingest" \\
  -F "file=@frame.jpg" \\
  -F "captured_at=2026-10-19T12:00" \\
  -F "timezone=Europe/Moscow" \\
  -F "camera_name=Камера" \\
  -F "building_hint=1.3"`}</pre>
                  <p className="settings-hint">
                    Поля: file, captured_at, timezone, camera_id | camera_name, building_hint, video_interval_sec
                  </p>
                </div>
              </Panel>

              <Panel title="Webhook наружу">
                <div className="settings-form" data-tour-id="settings-webhook-panel">
                  <div className="settings-form-row">
                    <label className="settings-field">
                      <span>Имя</span>
                      <input value={hookName} onChange={(e) => setHookName(e.target.value)} />
                    </label>
                    <label className="settings-field settings-field-grow">
                      <span>URL</span>
                      <input
                        value={hookUrl}
                        onChange={(e) => setHookUrl(e.target.value)}
                        placeholder="https://…"
                      />
                    </label>
                    <label className="settings-field">
                      <span>Секрет</span>
                      <input
                        type="password"
                        value={hookSecret}
                        onChange={(e) => setHookSecret(e.target.value)}
                        autoComplete="off"
                      />
                    </label>
                  </div>
                  <div className="settings-checks">
                    <label className="settings-check">
                      <input
                        type="checkbox"
                        checked={hookEvents.includes('new_frame')}
                        onChange={(e) =>
                          setHookEvents((ev) =>
                            e.target.checked ? [...ev, 'new_frame'] : ev.filter((x) => x !== 'new_frame'),
                          )
                        }
                      />
                      <span>Новый кадр</span>
                    </label>
                    <label className="settings-check">
                      <input
                        type="checkbox"
                        checked={hookEvents.includes('new_warning')}
                        onChange={(e) =>
                          setHookEvents((ev) =>
                            e.target.checked
                              ? [...ev, 'new_warning']
                              : ev.filter((x) => x !== 'new_warning'),
                          )
                        }
                      />
                      <span>Предупреждение</span>
                    </label>
                  </div>
                  <div className="settings-form-actions">
                    <button type="button" className="admin-btn primary" disabled={!canManage} onClick={onAddWebhook}>
                      Добавить
                    </button>
                  </div>
                </div>
                {bundle.webhooks.length > 0 && (
                  <div className="admin-table-wrap">
                    <table className="admin-table">
                      <thead>
                        <tr>
                          <th>Имя</th>
                          <th>URL</th>
                          <th>События</th>
                          <th>Статус</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {bundle.webhooks.map((h) => (
                          <tr key={h.id}>
                            <td>{h.name}</td>
                            <td className="settings-url-cell">{h.url}</td>
                            <td>{h.events.join(', ')}</td>
                            <td>
                              <StatusPill status={h.status} />
                            </td>
                            <td className="settings-actions">
                              <button
                                type="button"
                                className="admin-btn"
                                onClick={() =>
                                  setBundle(updateExportWebhook(projectId, h.id, { enabled: !h.enabled }))
                                }
                              >
                                {h.enabled ? 'Пауза' : 'Вкл'}
                              </button>
                              <button
                                type="button"
                                className="admin-btn danger"
                                disabled={!canManage}
                                onClick={() => {
                                  if (denyUnlessTech()) return
                                  setBundle(removeExportWebhook(projectId, h.id))
                                }}
                              >
                                Удалить
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Panel>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
