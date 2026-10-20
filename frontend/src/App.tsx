import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { RequireAuth } from './auth/RequireAuth'
import { AppShell } from './components/AppShell'
import { TourProvider } from './tour/TourProvider'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { LoginPage } from './pages/LoginPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { SchedulePage } from './pages/SchedulePage'
import { AdminCatalogsIndex, AdminPage } from './pages/AdminPage'
import { AdminCatalogDetailPage } from './pages/AdminCatalogDetailPage'
import { ProjectCamerasPage } from './pages/ProjectCvPages'
import { SettingsPage } from './pages/SettingsPage'
import { ProfilePage } from './pages/ProfilePage'

/** Предупреждения живут третьей панелью на графике; старый URL сохраняем. */
function DeviationsToScheduleRedirect() {
  const { projectId } = useParams()
  return <Navigate to={`/projects/${projectId}/schedule?warnings=1`} replace />
}

function TourLayout() {
  return (
    <TourProvider>
      <AppShell />
    </TourProvider>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RequireAuth />}>
            <Route element={<TourLayout />}>
              <Route path="/" element={<AnalyticsPage />} />
              <Route path="/projects" element={<ProjectsPage />} />
              <Route path="/projects/:projectId/schedule" element={<SchedulePage />} />
              <Route path="/projects/:projectId/cameras" element={<ProjectCamerasPage />} />
              <Route path="/projects/:projectId/deviations" element={<DeviationsToScheduleRedirect />} />
              <Route path="/learning" element={<Navigate to="/" replace />} />
              <Route path="/admin" element={<AdminPage />}>
                <Route index element={<Navigate to="catalogs" replace />} />
                <Route path="catalogs" element={<AdminCatalogsIndex />} />
                <Route path="catalogs/:catalogKey" element={<AdminCatalogDetailPage />} />
              </Route>
              <Route path="/profile" element={<ProfilePage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
