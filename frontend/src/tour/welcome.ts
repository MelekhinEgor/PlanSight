/** Показ панели обучения после входа (sessionStorage). */
export const TRAINING_WELCOME_KEY = 'plansight.training.welcome.skipped'

export function readWelcomeSkipped(): boolean {
  try {
    return sessionStorage.getItem(TRAINING_WELCOME_KEY) === '1'
  } catch {
    return false
  }
}

export function markWelcomeSkipped() {
  try {
    sessionStorage.setItem(TRAINING_WELCOME_KEY, '1')
  } catch {
    /* игнорировать квоту */
  }
}

/** Сброс — панель снова откроется (после логина). */
export function resetTrainingWelcome() {
  try {
    sessionStorage.removeItem(TRAINING_WELCOME_KEY)
  } catch {
    /* ignore */
  }
}
