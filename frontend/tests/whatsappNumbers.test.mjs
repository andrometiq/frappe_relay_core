import test from 'node:test'
import assert from 'node:assert/strict'
import { hasManyNumbers, messageNumberTags, numberName, whatsappNumbers } from '../src/services/whatsappNumbers.js'

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

test('a thread names the number when it changes within one direction', () => {
  const capabilities = { whatsapp_numbers: [SALES, SUPPORT] }
  const rows = [['M1', 'WA-2', 'Incoming'], ['M2', 'WA-2', 'Outgoing'], ['M3', 'WA-1', 'Incoming'], ['M4', 'WA-1', 'Outgoing'],
    ['M5', 'WA-1', 'Incoming'], ['M6', 'TG-1', 'Incoming']].map(([name, channel, direction]) => ({ name, channel, direction }))
  assert.deepEqual(messageNumberTags(rows, capabilities),
    { M1: 'to Support line', M2: 'via Support line', M3: 'to Sales line', M4: 'via Sales line' })
  assert.deepEqual(messageNumberTags(rows, { whatsapp_numbers: [SALES] }), {})
})
