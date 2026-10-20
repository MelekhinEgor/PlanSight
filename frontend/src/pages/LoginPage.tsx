import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { DEMO_USERS_HINT } from '../auth/roles'
import { resetTrainingWelcome } from '../tour/welcome'

export function LoginPage() {
  const auth = useAuth()
  const navigate = useNavigate()

  const [login, setLogin] = useState('user')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (!auth.loading && auth.user) {
    return <Navigate to="/" replace />
  }

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await auth.login(login, password)
      resetTrainingWelcome()
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Неверный логин или пароль')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-screen">
      <div className="login-card" role="main">
        <div className="login-brand">
          <img src="/plansight-logo.png" alt="PlanSight" />
          <p>Контроль строительного графика по наблюдениям с камер</p>
        </div>

        <form className="login-form" onSubmit={onSubmit}>
          <h1>Вход в систему</h1>
          <label className="login-field">
            <span>Логин</span>
            <input
              name="login"
              autoComplete="username"
              value={login}
              onChange={(e) => setLogin(e.target.value)}
              placeholder="Логин"
              required
              autoFocus
            />
          </label>
          <label className="login-field">
            <span>Пароль</span>
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Пароль"
              required
            />
          </label>
          {error && <p className="login-error">{error}</p>}
          <button type="submit" className="login-submit" disabled={busy}>
            {busy ? 'Входим…' : 'Войти'}
          </button>
        </form>

        <div className="login-hint" data-tour-id="login-demo-roles">
          <b>Демо-доступ · роли</b>
          {DEMO_USERS_HINT.map((u) => (
            <p key={u.login}>
              <button
                type="button"
                className="login-hint-pick"
                onClick={() => {
                  setLogin(u.login)
                  setPassword(u.password)
                }}
              >
                <code>{u.login}</code> / <code>{u.password}</code>
              </button>
              <span>
                {u.role} — {u.note}
              </span>
            </p>
          ))}
        </div>
      </div>
    </div>
  )
}
