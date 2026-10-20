import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'

export function RequireAuth() {
  const auth = useAuth()
  const location = useLocation()

  if (auth.loading) {
    return (
      <div className="auth-boot" role="status">
        <img src="/plansight-logo.png" alt="" />
        <span>Загрузка…</span>
      </div>
    )
  }

  if (!auth.user) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return <Outlet />
}
