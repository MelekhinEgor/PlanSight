/**
 * Smoke-проверка сценариев доказательств v2 (Reports v2).
 * Запуск: npx tsx --test src/lib/stroginoDemoFrames.test.ts
 */
import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import {
  buildScenarioDecisionScheme,
  buildScenarioEvidence,
  isCameraBackedFinding,
  isEvidenceScenariosEnabled,
  isOffsiteAdminWork,
  listScenarioWarningRows,
  resolveScenarioCandidates,
  scenarioIdFromUiDeviationId,
  scenarioShortTitle,
} from './evidenceScenariosV2'

const demoActs = [
  { id: 'a1', name: 'Выемка грунта котлована', code: '1.9.1.3', planned_start: '2026-09-25', planned_end: '2026-11-10' },
  { id: 'a1b', name: 'Вывоз грунта из котлована', code: '1.9.1.35', planned_start: '2026-09-28', planned_end: '2026-11-15' },
  { id: 'a2', name: 'Буронабивные сваи', code: '1.9.1.4', planned_start: '2026-10-12', planned_end: '2026-11-25' },
  { id: 'a3', name: 'Выемка грунта котлована (дубль для проверки)', code: '1.9.1.99', planned_start: '2026-09-28', planned_end: '2026-11-15' },
  { id: 'a4', name: 'Буронабивные сваи', code: '1.3.1.1', planned_start: '2026-04-28', planned_end: '2026-06-11' },
  { id: 'a5', name: 'Разрешение на строительство корпуса 1.3', code: '1.9.1.1', planned_start: '2026-08-28', planned_end: '2026-08-28' },
]

function collectUserFacingText(ev: ReturnType<typeof buildScenarioEvidence>): string {
  const m = ev.demo_meta
  return [
    ev.explanation_ru,
    ...(ev.limitations || []),
    m?.brief,
    m?.expected,
    m?.observed_hint,
    m?.rule_result_ru,
    m?.delay_note,
    m?.work_match_notice,
    m?.normative_formulation,
    m?.normative_observation,
    m?.next_action,
    ...(m?.forecast_block_reasons || []),
  ]
    .filter(Boolean)
    .join('\n')
}

test('scenarios gated to Strogino only', () => {
  assert.equal(isEvidenceScenariosEnabled({ id: 'strogino', slug: 'strogino', name: 'ЖК' }), true)
  assert.equal(isEvidenceScenariosEnabled({ id: 'parkline', name: 'Парклайн' }), false)
})

test('admin permit work is offsite and not a camera finding', () => {
  assert.equal(isOffsiteAdminWork('Разрешение на строительство корпуса 1.3'), true)
  assert.equal(isOffsiteAdminWork('Выемка грунта котлована'), false)
  assert.equal(isCameraBackedFinding({ signal_kind: 'SCHEDULE_EDITORIAL' }), false)
  assert.equal(isCameraBackedFinding({ signal_kind: 'DEMO_STATIC_FINDING', has_evidence_frames: true }), true)
})

test('three scenario rows linked to корпус 1.3 work names', () => {
  const rows = listScenarioWarningRows(demoActs)
  assert.equal(rows.length, 3)
  assert.equal(rows[0].schedule_item_name, 'Выемка грунта котлована')
  assert.equal(rows[1].schedule_item_name, 'Буронабивные сваи')
  assert.equal(rows[2].schedule_item_name, 'Вывоз грунта из котлована')
  assert.equal(rows[0].schedule_item_id, 'a1')
  assert.equal(rows[2].schedule_item_id, 'a1b')
  assert.equal(rows[0].match_label, 'Выемка грунта котлована')
  assert.ok(rows.every((r) => r.bucket === 'attention'))
  assert.ok(rows.every((r) => r.review_status === 'Требует проверки'))
  assert.equal(rows[0].observation_period, '25.09.2026 — 10.11.2026')
  assert.equal(rows[1].observation_period, '12.10.2026 — 25.11.2026')
  assert.equal(rows[2].observation_period, '28.09.2026 — 15.11.2026')
})

test('scenario periods fall back when schedule has no dates', () => {
  const rows = listScenarioWarningRows([])
  assert.equal(rows[2].schedule_item_name, 'Вывоз грунта из котлована')
  assert.equal(rows[2].observation_period, '28.09.2026 — 15.11.2026')
  assert.ok(!/не определён/i.test(rows[2].observation_period))
})

test('candidates prefer preferred codes, not permit or old piles', () => {
  const piles = resolveScenarioCandidates('pile-foundation', demoActs)
  assert.equal(piles.length, 1)
  assert.equal(piles[0].code, '1.9.1.4')
  assert.ok(!resolveScenarioCandidates('equipment-composition', demoActs).some((a) => /разрешен/i.test(a.name || '')))
})

test('equipment forecast is +8 with assumed KSG link', () => {
  const ev = buildScenarioEvidence('equipment-composition', demoActs)
  assert.ok((ev.demo_meta?.brief || '').length > 20)
  assert.ok((ev.demo_meta?.brief || '').length < 180)
  assert.ok((ev.explanation_ru || '').length > 80)
  assert.ok((ev.explanation_ru || '').length < 650)
  assert.ok(!/вердикт/i.test(ev.explanation_ru || ''))
  assert.ok(/14\.09\.2023/.test(ev.explanation_ru || ''))
  assert.ok(/предполагаем/i.test(ev.explanation_ru || ''))
  assert.ok(/\+8/.test(ev.demo_meta?.delay_note || ''))
  assert.equal(ev.demo_meta?.forecast_status, 'Рассчитан')
  assert.equal(ev.demo_meta?.forecast_impact_days, 8)
  assert.equal(ev.demo_meta?.forecast_finish, '2027-01-30')
  assert.ok(ev.demo_meta?.forecast_trace)
  assert.equal(ev.demo_meta?.task_link_status, 'Предполагаемая')
  assert.ok((ev.demo_meta?.observation_stamp || '').includes('14.09.2023'))
  assert.ok((ev.demo_meta?.plan_window || '').includes('25.09.2026'))
  assert.ok((ev.demo_meta?.normative_formulation || '').length > 40)
  assert.ok(ev.demo_meta?.normative_refs?.length)
  assert.equal(ev.schedule_item?.id, 'a1')
  assert.equal(ev.match_status, 'AMBIGUOUS')
  assert.ok((ev.frames?.[0]?.scenario_time_label || '').includes('14.09.2023'))
})

test('all three scenarios have calculated delay forecasts', () => {
  const equipment = buildScenarioEvidence('equipment-composition', demoActs)
  const pile = buildScenarioEvidence('pile-foundation', demoActs)
  const haulage = buildScenarioEvidence('haulage-tempo', demoActs)

  assert.equal(equipment.demo_meta?.forecast_status, 'Рассчитан')
  assert.equal(equipment.demo_meta?.forecast_impact_days, 8)
  assert.ok(/\+8/.test(equipment.demo_meta?.delay_note || ''))

  assert.equal(pile.demo_meta?.forecast_status, 'Рассчитан')
  assert.equal(pile.demo_meta?.forecast_impact_days, 12)
  assert.equal(pile.demo_meta?.forecast_finish, '2026-12-07')
  assert.ok(/\+12/.test(pile.demo_meta?.delay_note || ''))
  assert.ok(pile.demo_meta?.forecast_trace)

  assert.equal(haulage.demo_meta?.forecast_status, 'Рассчитан')
  assert.equal(haulage.demo_meta?.forecast_impact_days, 10)
  assert.equal(haulage.demo_meta?.forecast_finish, '2026-11-25')
  assert.ok(/\+10/.test(haulage.demo_meta?.delay_note || ''))
  assert.equal(haulage.demo_meta?.display_status, 'Требует проверки')

  const scheme = buildScenarioDecisionScheme('haulage-tempo')
  assert.ok(scheme.some((n) => /\+10\s*дн/i.test(n.result || '')))
  const pileScheme = buildScenarioDecisionScheme('pile-foundation')
  assert.ok(pileScheme.some((n) => /\+12\s*дн/i.test(n.result || '')))
})

test('decision scheme walks camera → work → schedule → normative', () => {
  const scheme = buildScenarioDecisionScheme('pile-foundation')
  assert.ok(scheme.some((n) => /наблюден/i.test(n.title)))
  assert.ok(scheme.some((n) => /ксг/i.test(n.title)))
  assert.ok(scheme.some((n) => /срок/i.test(n.title)))
  assert.ok(scheme.some((n) => /норматив/i.test(n.title)))
  assert.equal(scenarioIdFromUiDeviationId(-900002), 'pile-foundation')
})

test('pile scenario explains camera reason without magic delay days', () => {
  const ev = buildScenarioEvidence('pile-foundation', demoActs)
  assert.ok(/по кадрам/i.test(ev.explanation_ru || ''))
  assert.ok(/буров/i.test(ev.explanation_ru || ''))
  assert.ok(/планов/i.test(ev.explanation_ru || ''))
  assert.ok(/предполагаем/i.test(ev.explanation_ru || ''))
  assert.ok(!/нашли и сопоставили/i.test(ev.explanation_ru || ''))
  const frame2 = ev.frames?.[1]
  assert.ok(frame2)
  const rigs = (frame2?.detections || []).filter((d) => /буров|свай/i.test(d.label_ru || ''))
  assert.equal(rigs.length, 2)
  assert.ok(!(frame2?.detections || []).some((d) => /кран/i.test(d.label_ru || '')))
})

test('user-facing texts avoid forbidden site-absence and English codes', () => {
  const ids = ['equipment-composition', 'pile-foundation', 'haulage-tempo'] as const
  for (const sid of ids) {
    const ev = buildScenarioEvidence(sid, demoActs)
    const text = collectUserFacingText(ev)
    assert.ok(!/отсутствует на площадке/i.test(text), sid)
    assert.ok(!/на площадке отсутствует/i.test(text), sid)
    assert.ok(!/нет на площадке/i.test(text), sid)
    assert.ok(!/\bDEMO\b/.test(text), sid)
    assert.ok(!/\bNEEDS_REVIEW\b/.test(text), sid)
    assert.ok(!/EQUIPMENT_COMPOSITION|PILE_FOUNDATION|HAULAGE_TEMPO/.test(text), sid)
    assert.ok(/предполагаем/i.test(ev.demo_meta?.task_link_status || '') || /предполагаем/i.test(text), sid)
    const title = scenarioShortTitle(sid)
    assert.ok(/[а-яА-ЯёЁ]/.test(title), sid)
    assert.ok(!/^[A-Z0-9_-]+$/.test(title), sid)
  }
})
