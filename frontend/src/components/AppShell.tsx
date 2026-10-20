import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import { Bell, ChevronDown } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { appRoleLabel, appRoleOf, profileAvatarSrc } from '../auth/roles'
import { registerTourBridge } from '../tour/tourBridge'
import { resetTrainingWelcome } from '../tour/welcome'
import { ProjectTree } from './ProjectTree'
import { TrainingFab } from './TrainingFab'
import { todayIsoMoscow } from '../labels/ru'

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

function formatPeriodCaption() {
  const to = todayIsoMoscow()
  const fromDate = new Date()
  fromDate.setDate(fromDate.getDate() - 46)
  const fromParts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/Moscow',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(fromDate)
  const get = (type: Intl.DateTimeFormatPartTypes) => fromParts.find((p) => p.type === type)?.value || '01'
  const from = `${get('year')}-${get('month')}-${get('day')}`
  const fmt = (iso: string) => {
    const [y, m, d] = iso.split('-')
    return `${d}.${m}.${y}`
  }
  return `${fmt(from)} — ${fmt(to)}`
}

export function AppShell() {
  const auth = useAuth()
  const [sideOpen, setSideOpen] = useState(readSideOpen)
  const [profileOpen, setProfileOpen] = useState(false)
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { projectId } = useParams()
  const showSide = Boolean(pathname.match(/^\/projects\/[^/]+\/(schedule|cameras|deviations)/))
  const displayName = auth.user?.name || 'Пользователь'
  const displayRole = auth.user?.role || appRoleLabel(appRoleOf(auth.user))
  const displayInitials = auth.user?.initials || '??'

  useEffect(() => {
    try {
      sessionStorage.setItem(SIDE_KEY, sideOpen ? '1' : '0')
    } catch {
      /* ignore */
    }
  }, [sideOpen])

  useEffect(() => {
    const collapse = () => setSideOpen(false)
    window.addEventListener('plansight:sidebar-collapse', collapse)
    return () => window.removeEventListener('plansight:sidebar-collapse', collapse)
  }, [])

  useEffect(() => {
    return registerTourBridge({
      shell: {
        openProfileMenu: () => setProfileOpen(true),
        closeProfileMenu: () => setProfileOpen(false),
        switchDemoUser: async (login: string) => {
          setProfileOpen(false)
          await auth.switchDemoUser(login)
        },
      },
    })
  }, [auth])

  const go = (path: string) => {
    setProfileOpen(false)
    navigate(path)
  }

  const onLogout = async () => {
    setProfileOpen(false)
    resetTrainingWelcome()
    await auth.logout()
    navigate('/login', { replace: true })
  }

  const toggleSide = () => setSideOpen((v) => !v)

  return (
    <div className="app-shell">
      <header className="topbar is-unified">
        <div className="topbar-left">
          <Link to="/" className="brand" aria-label="PlanSight — на главную">
            <img className="brand-logo-full" src="/plansight-logo.png" alt="PlanSight" />
          </Link>
          <nav className="top-nav" aria-label="Разделы">
            <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
              Аналитика
            </NavLink>
            <NavLink to="/projects" className={({ isActive }) => (isActive ? 'active' : '')}>
              Проекты
            </NavLink>
          </nav>
        </div>
        <div className="top-actions is-cluster">
          <button className="date-button period-chip" type="button" title="Период анализа">
            <span>{formatPeriodCaption()}</span>
          </button>
          <button className="notify-button has-badge" type="button" aria-label="Уведомления" title="Уведомления">
            <Bell size={16} strokeWidth={1.8} />
          </button>
          <div className={`profile-menu-wrap${profileOpen ? ' is-open' : ''}`} data-tour-id="profile-menu-wrap">
            <button
              type="button"
              className="profile-button"
              aria-expanded={profileOpen}
              onClick={() => setProfileOpen((v) => !v)}
              data-tour-id="profile-menu-button"
            >
              <span className="avatar has-photo" aria-hidden={!displayName}>
                <img src={profileAvatarSrc(auth.user)} alt="" />
                <span className="avatar-fallback">{displayInitials}</span>
              </span>
              <span className="profile-copy" data-tour-id="profile-role-label">
                <b>{displayName}</b>
                <small>{displayRole}</small>
              </span>
              <ChevronDown
                size={14}
                strokeWidth={1.8}
                className={`ui-chevron${profileOpen ? ' is-open' : ''}`}
                aria-hidden
              />
            </button>
            {profileOpen && (
              <>
                <button
                  type="button"
                  className="profile-menu-backdrop"
                  aria-label="Закрыть меню"
                  onClick={() => setProfileOpen(false)}
                />
                <div className="profile-menu" role="menu" data-tour-id="profile-menu">
                  <button type="button" role="menuitem" onClick={() => go('/profile')} data-tour-id="profile-menu-cabinet">
                    Личный кабинет
                  </button>
                  <button type="button" role="menuitem" onClick={() => go('/admin')} data-tour-id="profile-menu-admin">
                    Администрирование
                  </button>
                  <button type="button" role="menuitem" onClick={() => go('/settings')} data-tour-id="profile-menu-settings">
                    Настройки
                  </button>
                  <button type="button" role="menuitem" className="profile-menu-logout" onClick={() => void onLogout()}>
                    Выйти
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
      <TrainingFab />
    </div>
  )
}
