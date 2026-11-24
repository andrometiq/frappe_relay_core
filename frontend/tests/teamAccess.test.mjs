import test from 'node:test'
import assert from 'node:assert/strict'
import { ALL, GROUP, RECORD, accessModes, accessSummary, businessRows, fieldLabel, teamDraft } from '../src/services/teamAccess.js'

test('a type with a grouping field offers groups, a type without one offers records', () => {
  assert.deepEqual(accessModes({ grouping_fields: ['customer_group'] }), [GROUP, RECORD, ALL])
  assert.deepEqual(accessModes({ grouping_fields: [] }), [RECORD, ALL])
  assert.equal(fieldLabel('customer_group'), 'Customer Group')
})

test('saved rows become one draft entry per type and go back to the same rows', () => {
  const team = { name: 'North-001', title: 'North', members: ['a@example.invalid'], business: [
    { business_doctype: 'Customer', access: GROUP, value: 'North' }, { business_doctype: 'Customer', access: GROUP, value: 'East' },
    { business_doctype: 'Supplier', access: ALL, value: '' }] }
  const draft = teamDraft(team)
  assert.deepEqual(draft.types, [{ doctype: 'Customer', mode: GROUP, values: ['North', 'East'] }, { doctype: 'Supplier', mode: ALL, values: [] }])
  assert.deepEqual(businessRows(draft.types), team.business)
  assert.deepEqual(businessRows([{ doctype: 'Item', mode: RECORD, values: [] }]), [], 'Nothing picked gives no rows')
  assert.deepEqual(teamDraft({}), { name: '', title: '', members: [], types: [] })
})

test('the team list says what each type covers', () => {
  const label = doctype => ({ Customer: 'Customers' })[doctype] || doctype
  assert.deepEqual(accessSummary([{ business_doctype: 'Customer', all: false, groups: 3, records: 1 },
    { business_doctype: 'Supplier', all: true, groups: 0, records: 0 }, { business_doctype: 'Item', all: false, groups: 0, records: 0 }], label),
  ['Customers: 3 groups, 1 record', 'All Supplier', 'Item: nothing picked'])
})

test('a type saved with both groups and records keeps both', () => {
  const business = [{ business_doctype: 'Customer', access: GROUP, value: 'North' }, { business_doctype: 'Customer', access: RECORD, value: 'C1' }]
  const draft = teamDraft({ business })
  assert.deepEqual(draft.types.map(type => [type.mode, type.values]), [[GROUP, ['North']], [RECORD, ['C1']]])
  assert.deepEqual(businessRows(draft.types), business)
})
