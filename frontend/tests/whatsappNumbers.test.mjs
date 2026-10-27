import test from 'node:test'
import assert from 'node:assert/strict'
import { effectiveNumber, hasManyNumbers, hoursLeft, messageNumberTags, numberName, sendNumberChoice, whatsappNumbers, windowHint } from '../src/services/whatsappNumbers.js'

const SALES = { name: 'WA-1', label: 'Sales line', address: '+91 90030 12345' }
const SUPPORT = { name: 'WA-2', label: 'Support line', address: '+91 90030 67890' }

test('number tags and pickers show only on a site with two or more numbers', () => {
  assert.equal(hasManyNumbers({}), false)
  assert.equal(hasManyNumbers({ whatsapp_numbers: [SALES] }), false)
  assert.equal(hasManyNumbers({ whatsapp_numbers: [SALES, SUPPORT] }), true)
  assert.deepEqual(whatsappNumbers(null), [])
})

test('a tag names only a number of the site', () => {
  const capabilities = { whatsapp_numbers: [SALES, SUPPORT] }
  assert.equal(numberName(capabilities, 'WA-2'), 'Support line')
  assert.equal(numberName(capabilities, 'TG-1'), '')
  assert.equal(numberName(capabilities, undefined), '')
})

test('Send via marks where the customer wrote, closed windows and new numbers as template only', () => {
  const open = sendNumberChoice({ channel: 'WA-1', label: 'Sales line', has_chat: true, window: { open: true, remaining_seconds: 12.2 * 3600 } }, 'WA-1')
  assert.deepEqual([open.status, open.templateOnly], ['Customer wrote here · 13 h left', false])
  const other = sendNumberChoice({ channel: 'WA-1', has_chat: true, window: { open: true, remaining_seconds: 60 } }, 'WA-2')
  assert.equal(other.status, 'Window open · 1 h left')
  const closed = sendNumberChoice({ channel: 'WA-2', has_chat: true, window: { open: false } }, 'WA-1')
  assert.deepEqual([closed.status, closed.templateOnly, closed.hasChat], ['Window closed · template only', true, true])
  const fresh = sendNumberChoice({ channel: 'WA-3', has_chat: false, window: { open: false } }, 'WA-1')
  assert.deepEqual([fresh.status, fresh.templateOnly, fresh.hasChat], ['No chat yet · template only', true, false])
})

test('a reply goes from the staff pick while it is a site number, else from the backend default', () => {
  const items = [{ channel: 'WA-1' }, { channel: 'WA-2' }]
  assert.equal(effectiveNumber(items, '', 'WA-2'), 'WA-2')
  assert.equal(effectiveNumber(items, 'WA-1', 'WA-2'), 'WA-1')
  assert.equal(effectiveNumber(items, 'WA-9', 'WA-2'), 'WA-2')
  assert.equal(effectiveNumber(items, '', 'WA-9'), 'WA-1')
  assert.equal(effectiveNumber([], '', ''), '')
})

test('the window hint follows the chosen number', () => {
  assert.equal(windowHint({ window: { open: true, remaining_seconds: 3 * 3600 } }), '24 h window open · 3 h left')
  assert.equal(windowHint({ window: { open: false, remaining_seconds: 0 } }), '')
  assert.equal(windowHint(null), '')
  assert.equal(hoursLeft({ window: { open: true, remaining_seconds: 90 } }), '1 h left')
})

test('a thread names the number when it changes within one direction', () => {
  const capabilities = { whatsapp_numbers: [SALES, SUPPORT] }
  const rows = [['M1', 'WA-2', 'Incoming'], ['M2', 'WA-2', 'Outgoing'], ['M3', 'WA-1', 'Incoming'], ['M4', 'WA-1', 'Outgoing'],
    ['M5', 'WA-1', 'Incoming'], ['M6', 'TG-1', 'Incoming']].map(([name, channel, direction]) => ({ name, channel, direction }))
  assert.deepEqual(messageNumberTags(rows, capabilities),
    { M1: 'to Support line', M2: 'via Support line', M3: 'to Sales line', M4: 'via Sales line' })
  assert.deepEqual(messageNumberTags(rows, { whatsapp_numbers: [SALES] }), {})
})
