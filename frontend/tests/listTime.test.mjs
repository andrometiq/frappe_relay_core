import test from 'node:test'
import assert from 'node:assert/strict'
import { listTime } from '../src/components/relativeTime.js'

const now = new Date(2026, 9, 27, 15, 30).getTime()
const at = (...parts) => new Date(...parts).toISOString()

test('the conversation list shows clock time today, then Yesterday, weekday and date', () => {
  assert.equal(listTime(at(2026, 9, 27, 9, 48), now), '09:48')
  assert.equal(listTime(at(2026, 9, 26, 23, 5), now), 'Yesterday')
  assert.equal(listTime(at(2026, 9, 21, 10, 0), now), new Date(2026, 9, 21).toLocaleDateString([], { weekday: 'short' }))
  assert.equal(listTime(at(2026, 9, 2, 10, 0), now), new Date(2026, 9, 2).toLocaleDateString([], { month: 'short', day: 'numeric' }))
  assert.match(listTime(at(2025, 9, 2, 10, 0), now), /2025/)
})

test('the conversation list time is empty for missing or invalid values', () => {
  assert.equal(listTime('', now), '')
  assert.equal(listTime('not a date', now), '')
})
