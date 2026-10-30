import test from 'node:test'
import assert from 'node:assert/strict'
import { createScrollHold } from '../src/components/messages/scrollHold.js'

// A thread viewport whose bubbles can grow after the first layout, like media and async parts do.
function thread(heights, clientHeight = 300) {
  const rows = heights.map((height, index) => ({ name: 'M' + index, height }))
  let top = 0
  const node = {
    clientHeight,
    get scrollHeight() { return Math.max(clientHeight, rows.reduce((sum, row) => sum + row.height, 0)) },
    get scrollTop() { return top },
    set scrollTop(value) { top = Math.max(0, Math.min(value, node.scrollHeight - clientHeight)) },
    getBoundingClientRect: () => ({ top: 0, bottom: clientHeight }),
    querySelectorAll: () => rows.map((row, index) => {
      const start = rows.slice(0, index).reduce((sum, item) => sum + item.height, 0) - top
      return { dataset: { message: row.name }, getBoundingClientRect: () => ({ top: start, bottom: start + row.height }) }
    }),
  }
  return { node, rows, gap: () => node.scrollHeight - node.scrollTop - clientHeight }
}

test('the newest message stays in view when bubbles grow after the first scroll', () => {
  const { node, rows, gap } = thread(Array(20).fill(50))
  const hold = createScrollHold(() => node)
  hold.toBottom()
  rows[3].height += 400
  rows[19].height += 120
  assert.notEqual(gap(), 0, 'growth alone leaves the reader above the end')
  hold.apply()
  assert.equal(gap(), 0)
  assert.equal(hold.isAtBottom, true)
})

test('an opened unread message keeps its place while media above it loads', () => {
  const { node, rows } = thread(Array(20).fill(50))
  const hold = createScrollHold(() => node)
  assert.equal(hold.toMessage('M10', 56), true)
  const place = () => node.querySelectorAll().find(row => row.dataset.message === 'M10').getBoundingClientRect().top
  assert.equal(place(), 56)
  rows[2].height += 300
  hold.apply()
  assert.equal(place(), 56)
  assert.equal(hold.isAtBottom, false)
})

test('a reader scroll replaces the hold, and scrolling back to the end follows new messages again', () => {
  const { node, rows, gap } = thread(Array(20).fill(50))
  const hold = createScrollHold(() => node)
  hold.toBottom()
  hold.scrolled()
  assert.equal(hold.isAtBottom, true, 'the scroll event of the code itself is not a reader scroll')
  node.scrollTop = 200
  hold.scrolled()
  assert.equal(hold.isAtBottom, false)
  rows[0].height += 100
  hold.apply()
  assert.equal(node.querySelectorAll().find(row => row.dataset.message === 'M4').getBoundingClientRect().top, 0)
  node.scrollTop = node.scrollHeight
  hold.scrolled()
  rows.push({ name: 'M20', height: 80 })
  hold.apply()
  assert.equal(gap(), 0)
})

test('a missing message keeps the previous hold', () => {
  const { node } = thread(Array(20).fill(50))
  const hold = createScrollHold(() => node)
  assert.equal(hold.toMessage('absent'), false)
  assert.equal(hold.isAtBottom, true)
})

test('before the newest page is loaded, a reader at the bottom keeps their message while a newer page appends', () => {
  const { node, rows, gap } = thread(Array(10).fill(50))
  const hold = createScrollHold(() => node, () => false)
  node.scrollTop = node.scrollHeight
  hold.scrolled()
  assert.equal(hold.isAtBottom, false)
  rows.push(...Array(10).fill(0).map((_, index) => ({ name: 'N' + index, height: 50 })))
  hold.apply()
  assert.equal(gap(), 500, 'the appended page stays below the reader')
})

test('a bottom hold never pins to the end while newer rows are not loaded', () => {
  const { node, rows } = thread(Array(10).fill(50))
  let end = false
  const hold = createScrollHold(() => node, () => end)
  node.scrollTop = 100
  assert.equal(hold.toBottom(), false)
  rows.push(...Array(10).fill(0).map((_, index) => ({ name: 'N' + index, height: 50 })))
  assert.equal(hold.apply(), false, 'a rows change must not push the reader to the newer-page sentinel')
  assert.equal(node.scrollTop, 100)
  end = true
  assert.equal(hold.apply(), true)
  assert.equal(node.scrollTop, node.scrollHeight - node.clientHeight)
})
