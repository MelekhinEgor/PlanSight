/** Локальные предпочтения пользователя (личный кабинет). */

export type ProfilePrefs = {
  displayName: string
  timezone: string
  notifyWarnings: boolean
  notifyDigest: boolean
}

const KEY = 'plansight.profile.prefs.v1'

const DEFAULTS: ProfilePrefs = {
  displayName: '',
  timezone: 'Europe/Moscow',
  notifyWarnings: true,
  notifyDigest: false,
}

export function loadProfilePrefs(login: string): ProfilePrefs {
  try {
    const raw = localStorage.getItem(`${KEY}.${login}`)
    if (!raw) return { ...DEFAULTS }
    const parsed = JSON.parse(raw) as Partial<ProfilePrefs>
    return { ...DEFAULTS, ...parsed }
  } catch {
    return { ...DEFAULTS }
  }
}

export function saveProfilePrefs(login: string, prefs: ProfilePrefs): void {
  try {
    localStorage.setItem(`${KEY}.${login}`, JSON.stringify(prefs))
  } catch {
    /* quota */
  }
}
