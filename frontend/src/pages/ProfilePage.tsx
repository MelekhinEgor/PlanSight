import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { appRoleLabel, appRoleOf, canManageDataSources, profileAvatarSrc } from '../auth/roles'
import { loadProfilePrefs, saveProfilePrefs, type ProfilePrefs } from '../lib/profile/profilePrefsStore'

function rbacLabel(role?: string): string {
  switch (role) {
    case 'admin':
      return 'Администратор'
    case 'operator':
      return 'Оператор'
    case 'viewer':
      return 'Наблюдатель'
    default:
      return role || '—'
  }
}

export function ProfilePage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const user = auth.user
  const [prefs, setPrefs] = useState<ProfilePrefs>(() =>
    user ? loadProfilePrefs(user.login) : loadProfilePrefs(''),
  )
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (user) setPrefs(loadProfilePrefs(user.login))
  }, [user?.login])

  if (!user) {
    return (
      <div className="admin-page profile-page">
        <div className="admin-head">
          <div>
            <h1>Личный кабинет</h1>
            <p>Сессия не найдена</p>
          </div>
        </div>
      </div>
    )
  }

  const displayName = prefs.displayName.trim() || user.name
  const isLocalToken = (auth.token || '').startsWith('local.')

  const onSave = () => {
    saveProfilePrefs(user.login, prefs)
    setSaved(true)
    window.setTimeout(() => setSaved(false), 2500)
  }

  const onLogout = async () => {
    await auth.logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="profile-page" data-tour-id="profile-page">
      <div className="profile-hero">
        <div className="profile-hero-bg" aria-hidden />
        <div className="profile-hero-inner">
          <button type="button" className="profile-back" onClick={() => navigate(-1)} aria-label="Назад">
            ←
          </button>
          <div className="profile-identity">
            <span className="avatar has-photo profile-avatar" aria-hidden>
              <img src={profileAvatarSrc(user)} alt="" />
              <span className="avatar-fallback">{user.initials}</span>
            </span>
            <div className="profile-identity-text">
              <h1>{displayName}</h1>
              <div className="profile-chips" data-tour-id="profile-role-chips">
                <span className="profile-chip">{user.role}</span>
                <span className="profile-chip is-soft">{appRoleLabel(appRoleOf(user))}</span>
                <span className="profile-chip is-soft">{rbacLabel(user.rbac_role)}</span>
                {canManageDataSources(user) && (
                  <span className="profile-chip is-ok">Источники данных</span>
                )}
              </div>
              <p className="profile-login">@{user.login}</p>
            </div>
          </div>
          <button type="button" className="profile-logout" onClick={() => void onLogout()}>
            Выйти
          </button>
        </div>
      </div>

      {saved && (
        <div className="profile-toast" role="status">
          Сохранено
        </div>
      )}

      <div className="profile-main">
        <section className="profile-block">
          <header className="profile-block-head">
            <h2>Предпочтения</h2>
            <p>Только в этом браузере</p>
          </header>
          <div className="profile-fields">
            <label className="profile-field">
              <span>Отображаемое имя</span>
              <input
                value={prefs.displayName}
                onChange={(e) => setPrefs((p) => ({ ...p, displayName: e.target.value }))}
                placeholder={user.name}
              />
            </label>
            <label className="profile-field">
              <span>Часовой пояс</span>
              <input
                value={prefs.timezone}
                onChange={(e) => setPrefs((p) => ({ ...p, timezone: e.target.value }))}
                placeholder="Europe/Moscow"
              />
            </label>
          </div>
          <div className="profile-toggles">
            <label className="profile-toggle">
              <span>
                <b>Предупреждения</b>
                <i>Сигналы по наблюдениям</i>
              </span>
              <input
                type="checkbox"
                checked={prefs.notifyWarnings}
                onChange={(e) => setPrefs((p) => ({ ...p, notifyWarnings: e.target.checked }))}
              />
            </label>
            <label className="profile-toggle">
              <span>
                <b>Дневная сводка</b>
                <i>Краткий итог за день</i>
              </span>
              <input
                type="checkbox"
                checked={prefs.notifyDigest}
                onChange={(e) => setPrefs((p) => ({ ...p, notifyDigest: e.target.checked }))}
              />
            </label>
          </div>
          <div className="profile-block-foot">
            <button type="button" className="profile-save" onClick={onSave}>
              Сохранить
            </button>
          </div>
        </section>

        <section className="profile-block">
          <header className="profile-block-head">
            <h2>Учётная запись</h2>
          </header>
          <div className="profile-account-rows">
            <div className="profile-account-row">
              <div>
                <b>Логин</b>
                <span>{user.login}</span>
              </div>
            </div>
            <div className="profile-account-row">
              <div>
                <b>Пароль</b>
                <span>Смена через администратора</span>
              </div>
              <button type="button" className="profile-ghost-btn" disabled>
                Сменить
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
