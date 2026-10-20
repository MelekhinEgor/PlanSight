import type { AuthUser } from './types'

/** Продуктовые роли показа (поверх rbac_role): аналитик и технический специалист. */
export type AppRole = 'analyst' | 'technician' | 'admin'

export function appRoleOf(user: AuthUser | null | undefined): AppRole {
  const explicit = (user?.app_role || '').toLowerCase()
  if (explicit === 'analyst' || explicit === 'technician' || explicit === 'admin') return explicit
  const rbac = (user?.rbac_role || '').toLowerCase()
  if (rbac === 'admin') return 'admin'
  if (rbac === 'viewer') return 'analyst'
  // operator без app_role — аналитик (историческая учётка аналитика)
  return 'analyst'
}

export function appRoleLabel(role: AppRole): string {
  if (role === 'technician') return 'Технический специалист'
  if (role === 'admin') return 'Администратор'
  return 'Аналитик'
}

/** Подключение / удаление источников данных (камеры, файлы, API). */
export function canManageDataSources(user: AuthUser | null | undefined): boolean {
  const role = appRoleOf(user)
  return role === 'technician' || role === 'admin'
}

export const DEMO_USERS_HINT = [
  {
    login: 'user',
    password: 'plansight',
    name: 'Анна Соколова',
    role: 'Аналитик',
    note: 'аналитика и проверка сигналов',
  },
  {
    login: 'admin',
    password: 'plansight',
    name: 'Роман Белов',
    role: 'Технический специалист',
    note: 'источники данных и справочники',
  },
] as const

/** Аватар в шапке/профиле: аналитик — женщина, техспециалист — мужчина. */
export function profileAvatarSrc(user: AuthUser | null | undefined): string {
  const login = (user?.login || '').toLowerCase()
  const role = appRoleOf(user)
  if (login === 'admin' || role === 'technician' || role === 'admin') {
    return '/profile-avatar-man.jpg'
  }
  return '/profile-avatar-woman.jpg'
}

