/**
 * Совместимость со сценарием земляных работ.
 * Источник данных — evidenceScenariosV2 (пакет v2).
 */
export { demoClassColor } from './evidenceScenarioColors'
export type { DecisionSchemeNode } from './evidenceScenarioColors'

import {
  buildScenarioDecisionScheme,
  buildScenarioDecisionTrace,
  buildScenarioEvidence,
  isEvidenceScenariosEnabled,
  isScenarioUiDeviationId,
  listScenarioWarningRows,
  scenarioIdFromUiDeviationId,
  scenarioShortTitle,
  scenarioSubtitle,
  SCENARIO_UI_IDS,
} from './evidenceScenariosV2'
import type { DecisionTrace, FindingEvidence } from '../components/FindingDrawer'
import type { DemoProjectLike } from '../tour/demoProject'

export const STROGINO_DEMO_FINDING_KEY = 'equipment-composition'
export const STROGINO_DEMO_UI_DEVIATION_ID = SCENARIO_UI_IDS['equipment-composition']
export const STROGINO_DEMO_ASSET_BASE = '/demo/evidence-v2'

export function isStroginoDemoFramesEnabled(project: DemoProjectLike | null | undefined): boolean {
  return isEvidenceScenariosEnabled(project)
}

export function isStroginoDemoFindingKey(id: string | number | null | undefined): boolean {
  return isScenarioUiDeviationId(id) || String(id) === STROGINO_DEMO_FINDING_KEY
}

export function stroginoDemoFindingTitle(): string {
  return scenarioShortTitle('equipment-composition')
}

export function stroginoDemoProjectLabel(): string {
  return 'ЖК «Строгино 360»'
}

export function stroginoDemoSubtitle(): string {
  return scenarioSubtitle()
}

export function stroginoDemoWarningRow() {
  return listScenarioWarningRows()[0]
}

export function buildStroginoDemoEvidence(): FindingEvidence {
  return buildScenarioEvidence('equipment-composition')
}

export function buildStroginoDemoDecisionTrace(): DecisionTrace {
  return buildScenarioDecisionTrace('equipment-composition')
}

export function buildStroginoDemoDecisionScheme() {
  return buildScenarioDecisionScheme('equipment-composition')
}

export function schemeFromDecisionTrace(trace: DecisionTrace | null | undefined) {
  if (!trace?.user_logic?.length) return []
  return trace.user_logic
    .filter((s) => s.id !== 'limits')
    .slice(0, 8)
    .map((s) => ({
      id: s.id,
      title: s.title.replace(/\s*·\s*ДЕМО/gi, '').trim(),
      status: 'passed' as const,
      result: String(s.body || '').split(/[.;]/)[0]?.trim() || '—',
      detail: s.body,
    }))
}

export { scenarioIdFromUiDeviationId, listScenarioWarningRows, isScenarioUiDeviationId }
