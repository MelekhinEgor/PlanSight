/**
 * Smoke: npx tsx --test src/lib/reports/miniDocx.test.ts
 */
import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { buildDocxBlob, zipStore } from './miniDocx'
import { REPORT_DISCLAIMER } from './disclaimer'

test('zipStore produces PK signature', () => {
  const bytes = zipStore([{ name: 'a.txt', data: new TextEncoder().encode('hi') }])
  assert.equal(bytes[0], 0x50)
  assert.equal(bytes[1], 0x4b)
})

test('buildDocxBlob is a non-empty docx blob', async () => {
  const blob = buildDocxBlob([
    { type: 'h1', text: 'Тест' },
    { type: 'p', text: REPORT_DISCLAIMER },
    {
      type: 'image',
      // минимальный 1×1 PNG
      image: {
        data: Uint8Array.from(
          atob(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
          ),
          (c) => c.charCodeAt(0),
        ),
        ext: 'png',
        widthPx: 1,
        heightPx: 1,
        widthCm: 2,
      },
      caption: 'Тестовый кадр',
    },
  ])
  assert.ok(blob.size > 500)
  assert.ok(blob.type.includes('wordprocessingml') || blob.type.includes('octet'))
  const buf = new Uint8Array(await blob.arrayBuffer())
  assert.equal(buf[0], 0x50)
  assert.equal(buf[1], 0x4b)
})
