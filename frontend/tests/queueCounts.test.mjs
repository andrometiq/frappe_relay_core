import test from 'node:test'
import assert from 'node:assert/strict'
import { countLabel, queueCountParams } from '../src/services/queueCounts.js'

test('queue counts are exact below a thousand and hidden at zero', () => {
  assert.equal(countLabel(0), '')
  assert.equal(countLabel(undefined), '')
  assert.equal(countLabel(-2), '')
  assert.equal(countLabel(8), '8')
  assert.equal(countLabel(999), '999')
})

test('large queue counts stay short enough for a phone tab', () => {
  assert.equal(countLabel(1583), '1.6K')
  assert.equal(countLabel(12407), '12.4K')
})

test('counts follow the chosen channel and drop the all-channels choice', () => {
  assert.deepEqual(queueCountParams('Telegram'), { medium: 'Telegram' })
  assert.deepEqual(queueCountParams('all'), {})
  assert.deepEqual(queueCountParams(undefined), {})
})
