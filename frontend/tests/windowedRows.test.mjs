import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { anchoredScrollTop, rowWindow } from '../src/components/windowedRows.js'

const rows = (...names) => names.map(name => ({ name }))
const key = row => row.name

test('a list of 20,000 chats renders only the rows in view and the overscan', () => {
  const window = rowWindow({ count: 20000, rowHeight: 80, scrollTop: 800000, viewportHeight: 640, overscan: 6 })
  assert.deepEqual(window, { start: 9994, end: 10014 })
  assert.deepEqual(rowWindow({ count: 20000, rowHeight: 80, scrollTop: 0, viewportHeight: 640, overscan: 6 }), { start: 0, end: 14 })
  assert.deepEqual(rowWindow({ count: 5, rowHeight: 80, scrollTop: 0, viewportHeight: 640, overscan: 6 }), { start: 0, end: 5 })
})

test('an offset past the end, as before the browser clamps it, still renders the last rows', () => {
  const { start, end } = rowWindow({ count: 20, rowHeight: 80, scrollTop: 9000, viewportHeight: 640, overscan: 6 })
  assert.equal(end, 20)
  assert.ok(start <= end && start >= 0)
})

test('a new chat at the top keeps the reader in place when scrolled down, and shows at the top when at the top', () => {
  const previous = rows('a', 'b', 'c', 'd', 'e'), next = rows('new', 'a', 'b', 'c', 'd', 'e')
  assert.equal(anchoredScrollTop({ scrollTop: 170, rowHeight: 80, previous, next, key }), 250)
  assert.equal(anchoredScrollTop({ scrollTop: 0, rowHeight: 80, previous, next, key }), 0)
})

test('the chat in view that moves to the top does not drag the reader to the top', () => {
  const previous = rows('a', 'b', 'c', 'd', 'e'), next = rows('c', 'a', 'b', 'd', 'e')
  assert.equal(anchoredScrollTop({ scrollTop: 170, rowHeight: 80, previous, next, key }), 170)
})

test('chats removed above the reader, like read chats leaving Unread, move the offset up', () => {
  const previous = rows('a', 'b', 'c', 'd', 'e'), next = rows('c', 'd', 'e')
  assert.equal(anchoredScrollTop({ scrollTop: 250, rowHeight: 80, previous, next, key }), 90)
})

test('a next page below the reader or a fresh list with no shared rows keeps the offset', () => {
  assert.equal(anchoredScrollTop({ scrollTop: 170, rowHeight: 80, previous: rows('a', 'b', 'c'), next: rows('a', 'b', 'c', 'd'), key }), 170)
  assert.equal(anchoredScrollTop({ scrollTop: 170, rowHeight: 80, previous: rows('a', 'b', 'c'), next: rows('x', 'y'), key }), 170)
})

test('the inbox renders its chats through the windowed list and loads the next page before the end', async () => {
  const inbox = await readFile(new URL('../src/components/messages/InboxDirectory.vue', import.meta.url), 'utf8')
  assert.match(inbox, /<WindowedRows ref="rowList" class="directory-rows" :items="rows"/)
  assert.match(inbox, /v-for="row in shown"/)
  assert.doesNotMatch(inbox, /v-for="row in rows"/)
  assert.match(inbox, /root: \(\) => rowList\.value\?\.scroller/)
})
