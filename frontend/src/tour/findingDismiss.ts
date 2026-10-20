/** Пользователь закрыл карточку находки — тур не должен открывать её снова на том же шаге. */

let findingUserDismissed = false

export function markFindingUserDismissed(v = true) {
  findingUserDismissed = v
}

export function resetFindingUserDismissed() {
  findingUserDismissed = false
}

export function isFindingUserDismissed() {
  return findingUserDismissed
}
