/** Типы guided tour — оверлеи на реальных экранах продукта. */

export type TourSuccessCondition =
  | { type: 'manual' }
  | { type: 'route'; includes: string }
  | { type: 'click'; target: string; /** Пауза после клика, чтобы пользователь успел прочитать открытое */ pauseMs?: number }
  | { type: 'present'; target: string }
  | { type: 'event'; name: string }
  | { type: 'dwell'; target: string; minMs?: number; minRatio?: number }

export type TourStep = {
  id: string
  route: string
  target: string
  title: string
  text: string
  expectedAction: string
  successCondition: TourSuccessCondition
  /**
   * If the highlight target never appears, do not treat it as an error —
   * show a calm tip and let the user continue with «Далее».
   */
  optional?: boolean
  /** Дружелюбная подсказка, если опциональная цель отсутствует (вместо жёсткого warning). */
  missingHint?: string
}

export type TourScenario = {
  id: string
  title: string
  description: string
  /** Версионированный ключ localStorage для прогресса (напр. plansight.tour.quick.v3). */
  storageKey?: string
  steps: TourStep[]
}

export type TourProgress = {
  stepIndex: number
  completedStepIds: string[]
  finished: boolean
  updatedAt: string
}

export type TourState = {
  scenarioId: string | null
  stepIndex: number
  active: boolean
}
