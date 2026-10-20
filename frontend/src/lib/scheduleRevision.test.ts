/**
 * Smoke: npx tsx --test src/lib/scheduleRevision.test.ts
 */
import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import {
  applyRevisionPatches,
  applySessionScheduleRevision,
  clearSessionScheduleRevision,
  reviseScheduleOnConfirm,
  saveSessionScheduleRevision,
} from './scheduleRevision'

test('driver forecast shifts by impact days', () => {
  const result = reviseScheduleOnConfirm({
    activityId: 'a1',
    impactDays: 8,
    activities: [
      { id: 'a1', name: 'Выемка', planned_start: '2026-09-25', planned_end: '2026-11-10', forecast_end: null },
      { id: 'a2', name: 'Сваи', planned_start: '2026-11-12', planned_end: '2026-12-01', forecast_end: null },
    ],
    dependencies: [{ predecessor_activity_id: 'a1', successor_activity_id: 'a2', relation_type: 'FS', lag_days: 0 }],
  })
  assert.equal(result.status, 'revised')
  assert.equal(result.impactDays, 8)
  const driver = result.patches.find((p) => p.activityId === 'a1')
  assert.ok(driver)
  assert.equal(driver?.nextForecast, '2026-11-18')
  assert.ok(result.messageRu.includes('+8'))
})

test('successor float can absorb delay', () => {
  const result = reviseScheduleOnConfirm({
    activityId: 'a1',
    impactDays: 3,
    activities: [
      { id: 'a1', name: 'A', planned_start: '2026-10-01', planned_end: '2026-10-10', forecast_end: null },
      // большой зазор до старта B → резерв поглощает
      { id: 'a2', name: 'B', planned_start: '2026-11-01', planned_end: '2026-11-20', forecast_end: null },
    ],
    dependencies: [{ predecessor_activity_id: 'a1', successor_activity_id: 'a2', relation_type: 'FS', lag_days: 0 }],
  })
  assert.ok(result.absorbedByFloatDays >= 3)
  assert.equal(result.affectedSuccessors, 0)
  assert.equal(result.projectFinishDeltaDays, 0)
})

test('applyRevisionPatches updates forecast_end', () => {
  const acts = [
    { id: 'a1', planned_end: '2026-11-10', forecast_end: null as string | null },
    { id: 'a2', planned_end: '2026-12-01', forecast_end: null as string | null },
  ]
  const next = applyRevisionPatches(acts, [
    {
      activityId: 'a1',
      prevForecast: null,
      nextForecast: '2026-11-18',
      shiftedDays: 8,
      reason: 'driver',
    },
  ])
  assert.equal(next[0].forecast_end, '2026-11-18')
  assert.equal(next[1].forecast_end, null)
})

test('session revision roundtrip applies overlays', () => {
  const g = globalThis as typeof globalThis & { sessionStorage?: Storage }
  const mem = new Map<string, string>()
  g.sessionStorage = {
    getItem: (k) => mem.get(k) ?? null,
    setItem: (k, v) => {
      mem.set(k, String(v))
    },
    removeItem: (k) => {
      mem.delete(k)
    },
    clear: () => mem.clear(),
    key: () => null,
    length: 0,
  }
  const revision = reviseScheduleOnConfirm({
    activityId: 'a1',
    impactDays: 5,
    activities: [{ id: 'a1', planned_end: '2026-11-10', forecast_end: null }],
  })
  assert.equal(revision.status, 'revised')
  saveSessionScheduleRevision('proj-1', revision)
  const { activities, overlay } = applySessionScheduleRevision('proj-1', [
    { id: 'a1', planned_end: '2026-11-10', forecast_end: null as string | null },
  ])
  assert.ok(overlay)
  assert.equal(activities[0].forecast_end, '2026-11-15')
  clearSessionScheduleRevision('proj-1')
  const cleared = applySessionScheduleRevision('proj-1', [
    { id: 'a1', planned_end: '2026-11-10', forecast_end: null as string | null },
  ])
  assert.equal(cleared.overlay, null)
})
