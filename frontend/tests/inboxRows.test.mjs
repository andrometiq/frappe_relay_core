import test from 'node:test'
import assert from 'node:assert/strict'
import { mergeChangedRows, mergeFirstPage, newestActivity } from '../src/services/inboxRows.js'
import { listRefresh } from '../src/services/realtimeRefreshQueue.js'

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

test('receipts change no row, reads refresh the open row, new messages move rows and other changes reload', () => {
  assert.equal(listRefresh(new Set(['receipts'])), 'none')
  assert.equal(listRefresh(new Set(['reads', 'chats', 'receipts'])), 'selected')
  assert.equal(listRefresh(new Set(['messages'])), 'loaded')
  assert.equal(listRefresh(new Set(['messages', 'reads', 'receipts'])), 'loaded')
  assert.equal(listRefresh(new Set(['messages', 'reconnect'])), 'reload')
  assert.equal(listRefresh(new Set(['inbox'])), 'reload')
  assert.equal(listRefresh(new Set()), 'reload')
  assert.equal(listRefresh(undefined), 'reload')
})

test('changed rows reuse the shown row objects, so only their values re-render', () => {
  const rows = [{ name: 'A', unread: 0 }, { name: 'B', unread: 0 }]
  const merged = mergeChangedRows(rows, [{ name: 'B', unread: 3 }])
  assert.equal(merged[0], rows[1])
  assert.deepEqual(merged.map(row => [row.name, row.unread]), [['B', 3], ['A', 0]])
})

test('a fresh first page keeps older loaded rows and drops rows that left its range', () => {
  const row = (name, at, unread = 0) => ({ name, last_message_at: at, unread })
  const rows = [row('A', '2026-11-04 10:05', 1), row('B', '2026-11-04 10:04', 1), row('C', '2026-11-04 10:03'), row('D', '2026-11-04 09:00')]
  const merged = mergeFirstPage(rows, { items: [row('A', '2026-11-04 10:05'), row('C', '2026-11-04 10:03')], next: { after: 'cursor' } })
  assert.deepEqual(merged.map(item => item.name), ['A', 'C', 'D'])
  assert.equal(merged[0], rows[0])
  assert.equal(merged[0].unread, 0)
  assert.deepEqual(mergeFirstPage(rows, { items: [row('C', '2026-11-04 10:03')], next: null }).map(item => item.name), ['C'])
})
