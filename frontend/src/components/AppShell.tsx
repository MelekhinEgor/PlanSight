import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import { ChevronDown } from 'lucide-react'
import { ProjectTree } from './ProjectTree'
import { todayCaptionShort } from '../labels/ru'

const SIDE_KEY = 'plansight.sidebarOpen'

function readSideOpen(): boolean {
  try {
    const v = sessionStorage.getItem(SIDE_KEY)
    if (v === null) return true
    return v === '1'
  } catch {
    return true
  }
}

export function AppShell() {
  const [sideOpen, setSideOpen] = useState(readSideOpen)
  const [profileOpen, setProfileOpen] = useState(false)
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { projectId } = useParams()
  // ProjectShell на всех маршрутах модулей проекта
  const showSide = Boolean(pathname.match(/^\/projects\/[^/]+\/(schedule|cameras|deviations)/))

  useEffect(() => {
    try {
      sessionStorage.setItem(SIDE_KEY, sideOpen ? '1' : '0')
    } catch {
      /* игнорировать */
    }
  }, [sideOpen])

  const go = (path: string) => {
    setProfileOpen(false)
    navigate(path)
  }

  const toggleSide = () => setSideOpen(v => !v)

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <img className="brand-logo-full" src="/plansight-logo.png" alt="PlanSight" />
        </div>
        <nav className="top-nav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
            Аналитика
          </NavLink>
          <NavLink to="/projects" className={({ isActive }) => (isActive ? 'active' : '')}>
            Проекты
          </NavLink>
        </nav>
        <div className="top-actions">
          <button className="date-button" type="button" title="Сегодня (Москва)">
            ▣ <span>{todayCaptionShort()}</span>
          </button>
          <div className="user-separator" />
          <div className={`profile-menu-wrap${profileOpen ? ' is-open' : ''}`}>
            <button type="button" className="profile-button" aria-expanded={profileOpen} onClick={() => setProfileOpen(v => !v)}>
              <span className="avatar">ВШ</span>
              <span className="profile-copy">
                <b>Вероника Широкова</b>
                <small>Аналитик</small>
              </span>
              <ChevronDown size={14} strokeWidth={1.8} className={`ui-chevron${profileOpen ? ' is-open' : ''}`} aria-hidden />
            </button>
            {profileOpen && (
              <>
                <button type="button" className="profile-menu-backdrop" aria-label="Закрыть меню" onClick={() => setProfileOpen(false)} />
                <div className="profile-menu" role="menu">
                  <button type="button" role="menuitem" onClick={() => go('/profile')}>
                    Личный кабинет
                  </button>
                  <button type="button" role="menuitem" onClick={() => go('/admin')}>
                    Администрирование
                  </button>
                  <button type="button" role="menuitem" onClick={() => go('/settings')}>
                    Настройки
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </header>
      <div className={`app-body${!showSide ? ' is-side-hidden' : sideOpen ? '' : ' is-side-collapsed'}`}>
        {showSide && <ProjectTree collapsed={!sideOpen} onToggle={toggleSide} />}
        <main className="app-content" data-project-id={projectId || undefined}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
