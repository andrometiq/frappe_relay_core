import test from 'node:test'
import assert from 'node:assert/strict'
import { mergeChangedRows, newestActivity, onlyChangedRows } from '../src/services/inboxRows.js'

test('the newest activity falls back to creation for conversations without messages', () => {
  assert.equal(newestActivity([]), '')
  assert.equal(newestActivity([
    { name: 'A', last_message_at: '2026-10-27 09:00:00.000001' },
    { name: 'B', last_message_at: null, creation: '2026-10-27 10:00:00' },
    { name: 'C', last_message_at: '2026-10-26 23:00:00' },
  ]), '2026-10-27 10:00:00')
})

test('changed conversations move to the top once and keep their new values', () => {
  const rows = [{ name: 'A', unread: 0 }, { name: 'B', unread: 0 }, { name: 'C', unread: 0 }]
  const merged = mergeChangedRows(rows, [{ name: 'C', unread: 2 }, { name: 'D', unread: 1 }])
  assert.deepEqual(merged.map(row => [row.name, row.unread]), [['C', 2], ['D', 1], ['A', 0], ['B', 0]])
  assert.deepEqual(mergeChangedRows(rows, []), rows)
})

test('only message events use the partial refresh; reads, assignments and reconnects reload the page', () => {
  assert.equal(onlyChangedRows(new Set(['messages'])), true)
  assert.equal(onlyChangedRows(new Set(['messages', 'incoming'])), true)
  assert.equal(onlyChangedRows(new Set(['messages', 'reads'])), false)
  assert.equal(onlyChangedRows(new Set(['reconnect'])), false)
  assert.equal(onlyChangedRows(new Set(['inbox'])), false)
  assert.equal(onlyChangedRows(new Set()), false)
})
