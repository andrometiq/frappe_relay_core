import test from 'node:test'
import assert from 'node:assert/strict'
import { recordTitle, readableName } from '../src/services/recordTitle.js'

test('captions prefer business and person titles while preserving identifiers', () => {
  const record = { name: 'RELAY-CON-0000000026', full_name: 'Maya Rao' }
  assert.equal(recordTitle(record), 'Maya Rao')
  assert.equal(record.name, 'RELAY-CON-0000000026')
  assert.equal(recordTitle({ name: 'CUST-0026', title: 'Rao Textiles' }), 'Rao Textiles')
  assert.equal(recordTitle({ name: 'RELAY-TKT-0000000001', subject: 'Missing delivery' }), 'Missing delivery')
})
test('generated identifiers stay out of fallback captions without stripping meaningful numbers', () => {
  for (const value of ['RELAY-CH-0000000026', '1792867625249477656', 'a'.repeat(32), '']) assert.equal(readableName(value, 'Channel'), 'Channel')
  assert.equal(recordTitle({ title: 'Warehouse 26' }), 'Warehouse 26')
  assert.equal(recordTitle({ name: 'order_update' }), 'order_update')
})

test('local fixture run keys do not obscure names or alter stored records', () => {
  const row = {title:'Local C2 1792867625249477656'}
  assert.equal(recordTitle(row), 'Local C2')
  assert.equal(row.title, 'Local C2 1792867625249477656')
  assert.equal(recordTitle({title:'Account 1792867625249477656'}), 'Account 1792867625249477656')
})
