import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, NavLink, useLocation, useParams, useSearchParams } from 'react-router-dom'
import { ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react'
import { api, type ProjectObject } from '../api/client'

/** Служебные коды из графика → подпись для людей. */
function objectLabel(name: string): string {
  const key = name.trim().toLowerCase()
  if (key === 'common') return 'Общие работы'
  if (key === 'без корпуса') return 'Без корпуса'
  return name
}

function buildTree(objects: ProjectObject[]) {
  const children = new Map<string | null, ProjectObject[]>()
  objects.forEach(o => {
    const key = o.parent_id
    if (!children.has(key)) children.set(key, [])
    children.get(key)!.push({ ...o, name: objectLabel(o.name) })
  })
  children.forEach(list => list.sort((a, b) => a.name.localeCompare(b.name, 'ru')))
  return children
}

type Props = { collapsed: boolean; onToggle: () => void }

/** Сайдбар ProjectShell: структура + навигация по модулям. */
export function ProjectTree({ collapsed, onToggle }: Props) {
  const { projectId } = useParams()
  const { pathname } = useLocation()
  const [searchParams] = useSearchParams()
  const selectedObjectId = searchParams.get('objectId')
  const project = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.getProject(projectId!),
    enabled: Boolean(projectId),
  })
  const objects = useQuery({
    queryKey: ['project-objects', projectId],
    queryFn: () => api.getProjectObjects(projectId!),
    enabled: Boolean(projectId),
  })
  const [openStages, setOpenStages] = useState<Set<string>>(new Set())
  const [hydratedProject, setHydratedProject] = useState<string | null>(null)
  const tree = useMemo(() => buildTree(objects.data ?? []), [objects.data])
  const stages = tree.get(null) ?? []

  useEffect(() => {
    if (!projectId || !objects.data?.length) return
    if (hydratedProject === projectId) return
    setOpenStages(new Set(objects.data.filter(o => !o.parent_id).map(r => r.id)))
    setHydratedProject(projectId)
  }, [projectId, objects.data, hydratedProject])

  useEffect(() => {
    if (!projectId) setHydratedProject(null)
  }, [projectId])

  const toggleStage = (id: string) =>
    setOpenStages(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const scheduleHref = (objectId?: string | null) => {
    const base = `/projects/${projectId}/schedule`
    if (!objectId) return base
    return `${base}?objectId=${encodeURIComponent(objectId)}`
  }

  const onSchedule = pathname.includes('/schedule')
  const onCameras = pathname.includes('/cameras')
  const onDeviations = pathname.includes('/deviations')

  if (collapsed) {
    return (
      <aside className="side-nav is-collapsed" data-tour-id="project-shell">
        <button type="button" className="side-collapse-btn" onClick={onToggle} title="Показать панель" aria-label="Показать панель">
          <ChevronRight size={18} strokeWidth={2.6} aria-hidden />
        </button>
      </aside>
    )
  }

  return (
    <aside className="side-nav" data-tour-id="project-shell">
      <div className="side-nav-top">
        {projectId && project.data ? (
          <div className="side-section-label" title={project.data.name}>
            {project.data.name}
          </div>
        ) : (
          <div className="side-section-label">Структура</div>
        )}
        <button type="button" className="side-collapse-btn" onClick={onToggle} title="Скрыть панель" aria-label="Скрыть панель">
          <ChevronLeft size={18} strokeWidth={2.6} aria-hidden />
        </button>
      </div>

      {projectId && (
        <nav className="side-nav-list" aria-label="Разделы проекта" data-tour-id="project-modules">
          <NavLink to={scheduleHref(selectedObjectId)} className={() => (onSchedule ? 'active' : '')} end={false} data-tour-id="nav-schedule">
            Календарный график
          </NavLink>
          <NavLink to={`/projects/${projectId}/cameras`} className={() => (onCameras ? 'active' : '')} data-tour-id="nav-cameras">
            Камеры и зоны
          </NavLink>
          <NavLink to={`/projects/${projectId}/deviations`} className={() => (onDeviations ? 'active' : '')} data-tour-id="nav-deviations">
            Предупреждения
          </NavLink>
        </nav>
      )}

      {projectId && project.data ? (
        <div className="side-tree">
          <div className="side-section-label" style={{ marginTop: 10, fontSize: 10, opacity: 0.75 }}>
            Объекты
          </div>
          <Link to={scheduleHref(null)} className={`side-tree-row leaf${!selectedObjectId && onSchedule ? ' is-active' : ''}`}>
            <span className="side-twist" />
            <span>Весь проект</span>
          </Link>
          {stages.map(stage => {
            const open = openStages.has(stage.id)
            const kids = tree.get(stage.id) ?? []
            const hasKids = kids.length > 0
            const stageSelected = selectedObjectId === stage.id
            return (
              <div key={stage.id}>
                {hasKids ? (
                  <div className={`side-tree-row stage${stageSelected ? ' is-active' : ''}`}>
                    <button
                      type="button"
                      className="side-twist"
                      onClick={() => toggleStage(stage.id)}
                      aria-expanded={open}
                      aria-label={open ? 'Свернуть' : 'Развернуть'}
                      title={open ? 'Свернуть' : 'Развернуть'}
                    >
                      <ChevronDown size={14} strokeWidth={1.8} className={open ? 'side-chevron open' : 'side-chevron'} aria-hidden />
                    </button>
                    <Link to={scheduleHref(stage.id)} className="side-tree-label">
                      {stage.name}
                    </Link>
                  </div>
                ) : (
                  <Link to={scheduleHref(stage.id)} className={`side-tree-row stage${stageSelected ? ' is-active' : ''}`}>
                    <span className="side-twist">
                      <i className="side-twist-dot" aria-hidden />
                    </span>
                    <span>{stage.name}</span>
                  </Link>
                )}
                {hasKids &&
                  open &&
                  kids.map(leaf => {
                    const active = selectedObjectId === leaf.id
                    return (
                      <Link key={leaf.id} to={scheduleHref(leaf.id)} className={`side-tree-row leaf${active ? ' is-active' : ''}`}>
                        <span className="side-twist" />
                        <span>{leaf.name}</span>
                      </Link>
                    )
                  })}
              </div>
            )
          })}
        </div>
      ) : (
        <div className="side-empty">Выберите проект на вкладке «Проекты»</div>
      )}

      <div className="side-footer project-shell-footer">
        <b>PlanSight</b>
        <span>
          Стройка под контролем
          <br />с ИИ
        </span>
      </div>
    </aside>
  )
}
