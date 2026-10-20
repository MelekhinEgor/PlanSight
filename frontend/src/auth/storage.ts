import type { AuthSession, AuthUser } from './types'

const KEY = 'plansight.auth.session.v1'

export function loadSession(): AuthSession | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as AuthSession
    if (!parsed?.token || !parsed?.user?.login) return null
    return parsed
  } catch {
    return null
  }
}

export function saveSession(session: AuthSession) {
  try {
    localStorage.setItem(KEY, JSON.stringify(session))
  } catch {
    /* игнорировать квоту */
  }
}

export function clearSession() {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
}

export function authHeaders(): Record<string, string> {
  const s = loadSession()
  if (!s?.token) return {}
  return { Authorization: `Bearer ${s.token}` }
}

/** Локальный fallback, если API недоступен (VITE_DEMO_MODE / офлайн). */
const LOCAL_USERS: Array<AuthUser & { password: string }> = [
  {
    login: 'user',
    password: 'plansight',
    name: 'Анна Соколова',
    role: 'Аналитик',
    initials: 'АС',
    rbac_role: 'operator',
    app_role: 'analyst',
  },
  {
    login: 'admin',
    password: 'plansight',
    name: 'Роман Белов',
    role: 'Технический специалист',
    initials: 'РБ',
    rbac_role: 'admin',
    app_role: 'technician',
  },
]

export function localLogin(login: string, password: string): AuthSession | null {
  const key = login.trim().toLowerCase()
  const hit = LOCAL_USERS.find((u) => u.login === key && u.password === password)
  if (!hit) return null
  const { password: _p, ...user } = hit
  return { token: `local.${user.login}.${Date.now()}`, user }
}

/** Смена учебной учётки без пароля (обучение / локальный режим). */
export function localSwitchUser(login: string): AuthSession | null {
  const key = login.trim().toLowerCase()
  const hit = LOCAL_USERS.find((u) => u.login === key)
  if (!hit) return null
  const { password: _p, ...user } = hit
  return { token: `local.${user.login}.${Date.now()}`, user }
}
