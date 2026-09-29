import { NavLink, Navigate, Outlet, useNavigate } from 'react-router-dom'
import { getDefaultCatalogKey, getVisibleCatalogs } from '../admin/catalogs'

export function AdminPage(){
  const navigate=useNavigate()
  const catalogs=getVisibleCatalogs()

  return <div className="admin-page">
    <div className="admin-head">
      <button type="button" className="admin-back" onClick={()=>navigate(-1)} aria-label="Назад">←</button>
      <div>
        <h1>Администрирование</h1>
        <p>Справочники системы PlanSight</p>
      </div>
    </div>

    <div className="admin-layout" data-tour-id="admin-catalogs">
      <aside className="admin-nav" aria-label="Справочники">
        <div className="admin-nav-title">Справочники</div>
        <nav className="admin-nav-list">
          {catalogs.map(c=>(
            <NavLink
              key={c.key}
              to={`/admin/catalogs/${c.key}`}
              className={({isActive})=>isActive?'admin-nav-item active':'admin-nav-item'}
            >{c.name}</NavLink>
          ))}
        </nav>
      </aside>
      <div className="admin-body"><Outlet/></div>
    </div>
  </div>
}

export function AdminCatalogsIndex(){
  return <Navigate to={`/admin/catalogs/${getDefaultCatalogKey()}`} replace/>
}
