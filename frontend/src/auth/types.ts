export type AuthUser = {
  login: string
  name: string
  role: string
  initials: string
  rbac_role?: string
  /** Продуктовая роль: analyst | technician | admin */
  app_role?: string
}

export type AuthSession = {
  token: string
  user: AuthUser
}
