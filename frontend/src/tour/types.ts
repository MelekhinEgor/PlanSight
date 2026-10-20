/** Типы guided tour — оверлеи на реальных экранах продукта. */

import type { TourAction } from './tourBridge'

export type TourSuccessCondition =
  | { type: 'manual' }
  | { type: 'route'; includes: string }
  | { type: 'click'; target: string; /** Пауза после клика, чтобы пользователь успел прочитать открытое */ pauseMs?: number }
  | { type: 'present'; target: string }
  | { type: 'event'; name: string }
  | { type: 'dwell'; target: string; minMs?: number; minRatio?: number }
  | { type: 'auto'; /** авто-режим обучения: провайдер сам прогоняет actions/focusSequence */ }

export type TourFocusBeat = {
  target: string
  /** Запасная цель, если основная не появилась. */
  fallbackTarget?: string
  text?: string
  durationMs?: number
  pulse?: boolean
  /** Показать анимированный указатель на цель. */
  pointer?: boolean
  /** Действия перед этой подсветкой (фильтр, открытие вкладки и т.п.). */
  actions?: TourAction[]
  /** Сколько ждать появления цели (мс). */
  waitForMs?: number
}

export type TourStep = {
  id: string
  route: string
  target: string
  title: string
  text: string
  expectedAction: string
  successCondition: TourSuccessCondition
  /** Кадр маскота для этого шага (`/mascots/{id}.png`). */
  mascot?: string
  /**
   * If the highlight target never appears, do not treat it as an error —
   * show a calm tip and let the user continue with «Далее».
   */
  optional?: boolean
  /** Дружелюбная подсказка, если опциональная цель отсутствует (вместо жёсткого warning). */
  missingHint?: string
  /** Авто-режим: последовательность подсветок внутри сцены. */
  focusSequence?: TourFocusBeat[]
  /** Действия в начале сцены (до focusSequence). Предпочтительнее actions на beat. */
  actions?: TourAction[]
  /** Ориентировочная длительность сцены (мс), если нет auto-advance по focusSequence. */
  durationMs?: number
  /** Восстановить snapshot аналитики при выходе. */
  restoreOnExit?: boolean
}

export type TourScenario = {
  id: string
  title: string
  description: string
  /** Версионированный ключ localStorage для прогресса (напр. plansight.tour.quick.v3). */
  storageKey?: string
  /** auto — демонстрация с автодействиями; guided — обучение кликами. */
  mode?: 'guided' | 'auto'
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
