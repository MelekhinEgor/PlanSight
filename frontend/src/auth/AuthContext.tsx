import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { clearSession, loadSession, localLogin, localSwitchUser, saveSession } from './storage'
import type { AuthSession, AuthUser } from './types'

type AuthApi = {
  user: AuthUser | null
  token: string | null
  loading: boolean
  login: (login: string, password: string) => Promise<void>
  /** Смена учебной учётки (обучение / показ ролей). */
  switchDemoUser: (login: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthApi | null>(null)

async function apiLogin(login: string, password: string): Promise<AuthSession> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login, password }),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    let detail = text
    try {
      const j = JSON.parse(text)
      detail = typeof j.detail === 'string' ? j.detail : text
    } catch {
      /* keep */
    }
    throw new Error(detail || 'Неверный логин или пароль')
  }
  return (await res.json()) as AuthSession
}

async function apiMe(token: string): Promise<AuthUser> {
  const res = await fetch('/api/auth/me', {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('session expired')
  return (await res.json()) as AuthUser
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(() => loadSession())
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const boot = async () => {
      const saved = loadSession()
      if (!saved) {
        if (!cancelled) {
          setSession(null)
          setLoading(false)
        }
        return
      }
      // Локальные токены (офлайн) не валидируем на API
      if (saved.token.startsWith('local.')) {
        if (!cancelled) {
          setSession(saved)
          setLoading(false)
        }
        return
      }
      try {
        const user = await apiMe(saved.token)
        if (!cancelled) {
          const next = { token: saved.token, user }
          saveSession(next)
          setSession(next)
        }
      } catch {
        clearSession()
        if (!cancelled) setSession(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void boot()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (loginName: string, password: string) => {
    try {
      const next = await apiLogin(loginName, password)
      saveSession(next)
      setSession(next)
    } catch (err) {
      // Fallback: локальные учебные учётки, если backend недоступен
      const offline = localLogin(loginName, password)
      if (offline) {
        saveSession(offline)
        setSession(offline)
        return
      }
      throw err instanceof Error ? err : new Error('Неверный логин или пароль')
    }
  }, [])

  const switchDemoUser = useCallback(async (loginName: string) => {
    const key = loginName.trim().toLowerCase()
    // Известные учебные пароли — один пароль на все учебные учётки показа
    try {
      const next = await apiLogin(key, 'plansight')
      saveSession(next)
      setSession(next)
      return
    } catch {
      const offline = localSwitchUser(key) || localLogin(key, 'plansight')
      if (offline) {
        saveSession(offline)
        setSession(offline)
        return
      }
      throw new Error('Демо-учётка не найдена')
    }
  }, [])

  const logout = useCallback(async () => {
    const token = session?.token
    clearSession()
    setSession(null)
    if (token && !token.startsWith('local.')) {
      try {
        await fetch('/api/auth/logout', {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        })
      } catch {
        /* ignore */
      }
    }
  }, [session?.token])

  const api = useMemo<AuthApi>(
    () => ({
      user: session?.user ?? null,
      token: session?.token ?? null,
      loading,
      login,
      switchDemoUser,
      logout,
    }),
    [session, loading, login, switchDemoUser, logout],
  )

  return <AuthContext.Provider value={api}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth requires AuthProvider')
  return ctx
}
