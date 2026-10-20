/**
 * Smoke: npx tsx --test src/lib/scheduleImpact.test.ts
 */
import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import fixture from '../data/scheduleDelayPlus8Fixture.json'
import { calculateScheduleImpact } from './scheduleImpact'

test('fixture +8 calendar days is reproducible', () => {
  const s = fixture.scenario
  const result = calculateScheduleImpact({
    plannedFinish: s.plannedFinish,
    asOfDate: s.asOfDate,
    currentProgressPercent: s.currentProgressPercent,
    dailyProgressPercentagePoints: s.dailyProgressPercentagePoints,
    progressSnapshots: s.progressSnapshots,
    dayType: 'calendar_days',
  })
  assert.equal(result.status, 'calculated')
  if (result.status !== 'calculated') return
  assert.equal(result.forecastFinish, s.forecastFinish)
  assert.equal(result.impactDays, s.impactDays)
  assert.equal(result.remainingDurationCalendarDays, s.remainingDurationCalendarDays)
  assert.ok(result.calculationTrace)
  assert.ok(result.summaryRu.includes('+8'))
})

test('rate from snapshots matches fixture', () => {
  const s = fixture.scenario
  const result = calculateScheduleImpact({
    plannedFinish: s.plannedFinish,
    asOfDate: s.asOfDate,
    currentProgressPercent: s.currentProgressPercent,
    progressSnapshots: s.progressSnapshots,
    dayType: 'calendar_days',
  })
  assert.equal(result.status, 'calculated')
  if (result.status !== 'calculated') return
  assert.equal(result.impactDays, 8)
  assert.equal(result.forecastFinish, '2027-01-30')
})

test('missing progress blocks forecast', () => {
  const result = calculateScheduleImpact({
    plannedFinish: '2027-01-22',
    asOfDate: '2027-01-02',
    currentProgressPercent: 72,
    dayType: 'calendar_days',
  })
  assert.equal(result.status, 'not_calculated')
  if (result.status !== 'not_calculated') return
  assert.ok(result.reasons.some((r) => /измерен|скорост/i.test(r)))
})

test('changing rate changes impact', () => {
  const slow = calculateScheduleImpact({
    plannedFinish: '2027-01-22',
    asOfDate: '2027-01-02',
    currentProgressPercent: 72,
    dailyProgressPercentagePoints: 0.5,
  })
  const fast = calculateScheduleImpact({
    plannedFinish: '2027-01-22',
    asOfDate: '2027-01-02',
    currentProgressPercent: 72,
    dailyProgressPercentagePoints: 2,
  })
  assert.equal(slow.status, 'calculated')
  assert.equal(fast.status, 'calculated')
  if (slow.status !== 'calculated' || fast.status !== 'calculated') return
  assert.ok(slow.impactDays > fast.impactDays)
})
