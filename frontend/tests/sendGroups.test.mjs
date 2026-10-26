import test from 'node:test'
import assert from 'node:assert/strict'
import { groupSends } from '../src/services/sendGroups.js'

const row = (name, send_group, provider, status = 'Sent') =>
  ({ name, send_group, status, provider_context: { provider } })

test('rows without a send group stay as they are', () => {
  const rows = [row('a', null, 'WhatsApp'), row('b', '', 'WhatsApp')]
  assert.deepEqual(groupSends(rows), rows)
  assert.equal(groupSends(rows)[0], rows[0])
})

test('copies of one send show once at the first copy with every channel and its own status', () => {
  const rows = [row('a', 'g1', 'WhatsApp', 'Read'), row('b', null, 'WhatsApp'), row('c', 'g1', 'Telegram', 'Failed')]
  const grouped = groupSends(rows)
  assert.deepEqual(grouped.map(item => item.name), ['a', 'b'])
  assert.deepEqual(grouped[0].sends.map(item => [item.provider_context.provider, item.status]),
    [['WhatsApp', 'Read'], ['Telegram', 'Failed']])
  assert.equal(rows[0].sends, undefined)
})

test('different send groups stay separate and a single loaded copy stays a plain row', () => {
  const rows = [row('a', 'g1', 'WhatsApp'), row('b', 'g2', 'WhatsApp'), row('c', 'g1', 'Email')]
  const grouped = groupSends(rows)
  assert.deepEqual(grouped[0].sends.map(copy => copy.name), ['a', 'c'])
  assert.equal(grouped[1], rows[1])
})
