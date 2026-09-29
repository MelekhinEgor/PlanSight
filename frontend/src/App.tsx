import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { TourProvider } from './tour/TourProvider'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { SchedulePage } from './pages/SchedulePage'
import { AdminCatalogsIndex, AdminPage } from './pages/AdminPage'
import { AdminCatalogDetailPage } from './pages/AdminCatalogDetailPage'
import { ProjectCamerasPage, ProjectDeviationsPage } from './pages/ProjectCvPages'

function PlaceholderPage({title,text}:{title:string;text:string}){
  return <div className="admin-page"><div className="admin-head"><div><h1>{title}</h1><p>{text}</p></div></div></div>
}

export default function App(){
  return (
    <BrowserRouter>
      <TourProvider>
        <Routes>
          <Route element={<AppShell/>}>
            <Route path="/" element={<AnalyticsPage/>}/>
            <Route path="/projects" element={<ProjectsPage/>}/>
            <Route path="/projects/:projectId/schedule" element={<SchedulePage/>}/>
            <Route path="/projects/:projectId/cameras" element={<ProjectCamerasPage/>}/>
            <Route path="/projects/:projectId/deviations" element={<ProjectDeviationsPage/>}/>
            <Route path="/learning" element={<Navigate to="/" replace/>}/>
            <Route path="/admin" element={<AdminPage/>}>
              <Route index element={<Navigate to="catalogs" replace/>}/>
              <Route path="catalogs" element={<AdminCatalogsIndex/>}/>
              <Route path="catalogs/:catalogKey" element={<AdminCatalogDetailPage/>}/>
            </Route>
            <Route path="/profile" element={<PlaceholderPage title="Личный кабинет" text="Раздел личного кабинета будет доступен позже."/>}/>
            <Route path="/settings" element={<PlaceholderPage title="Настройки" text="Пользовательские настройки появятся в следующих итерациях."/>}/>
            <Route path="*" element={<Navigate to="/" replace/>}/>
          </Route>
        </Routes>
      </TourProvider>
    </BrowserRouter>
  )
}
