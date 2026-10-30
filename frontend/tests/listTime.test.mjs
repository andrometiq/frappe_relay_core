import test from 'node:test'
import assert from 'node:assert/strict'
import { listTime, dateTime } from '../src/components/relativeTime.js'

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

test('a full time reads as day, month and 24-hour clock time', () => {
  assert.equal(dateTime('2026-10-28 17:31:48.960076'), new Date(2026, 9, 28, 17, 31).toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }))
  assert.equal(dateTime(''), '')
  assert.equal(dateTime('not a time'), '')
})
