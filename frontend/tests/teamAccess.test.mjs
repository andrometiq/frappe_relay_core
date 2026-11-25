import test from 'node:test'
import assert from 'node:assert/strict'
import { ALL, GROUP, RECORD, accessModes, accessSummary, businessRows, draftType, fieldLabel, groupField, staleGroups, teamDraft } from '../src/services/teamAccess.js'

test('a type with a grouping field offers groups, a type without one offers records', () => {
  assert.deepEqual(accessModes({ grouping_fields: ['customer_group'] }), [GROUP, RECORD, ALL])
  assert.deepEqual(accessModes({ grouping_fields: [] }), [RECORD, ALL])
  assert.equal(fieldLabel('customer_group'), 'Customer Group')
})

test('saved rows become one draft entry per type and go back to the same rows', () => {
  const team = { name: 'North-001', title: 'North', members: ['a@example.invalid'], business: [
    { business_doctype: 'Customer', access: GROUP, value: 'North', grouping_field: 'customer_group' },
    { business_doctype: 'Customer', access: GROUP, value: 'East', grouping_field: 'customer_group' },
    { business_doctype: 'Supplier', access: ALL, value: '' }] }
  const draft = teamDraft(team)
  assert.deepEqual(draft.types, [{ doctype: 'Customer', mode: GROUP, values: ['North', 'East'], groupingField: 'customer_group' },
    { doctype: 'Supplier', mode: ALL, values: [], groupingField: '' }])
  assert.deepEqual(businessRows(draft.types), team.business, 'Groups go back with the grouping field they were picked under')
  assert.deepEqual(businessRows([{ doctype: 'Item', mode: RECORD, values: [] }]), [], 'Nothing picked gives no rows')
  assert.deepEqual(teamDraft({}), { name: '', title: '', members: [], types: [] })
})

test('the team list says what each type covers', () => {
  const label = doctype => ({ Customer: 'Customers' })[doctype] || doctype
  assert.deepEqual(accessSummary([{ business_doctype: 'Customer', all: false, groups: 3, records: 1 },
    { business_doctype: 'Supplier', all: true, groups: 0, records: 0 }, { business_doctype: 'Item', all: false, groups: 0, records: 0 }], label),
  ['Customers: 3 groups, 1 record', 'All Supplier', 'Item: nothing picked'])
})

test('a type saved with both groups and records in Desk shows twice so one can be removed', () => {
  const business = [{ business_doctype: 'Customer', access: GROUP, value: 'North', grouping_field: 'customer_group' },
    { business_doctype: 'Customer', access: RECORD, value: 'C1' }]
  const draft = teamDraft({ business })
  assert.deepEqual(draft.types.map(type => [type.mode, type.values]), [[GROUP, ['North']], [RECORD, ['C1']]])
  assert.deepEqual(businessRows(draft.types), business)
})

test('a business type is added once, with the grouping field it uses now', () => {
  const customer = { business_doctype: 'Customer', grouping_fields: ['customer_group', 'territory'] }
  const added = draftType([], customer)
  assert.deepEqual(added, { doctype: 'Customer', mode: GROUP, values: [], groupingField: 'customer_group' })
  assert.equal(draftType([added], customer), null, 'The same type cannot be added twice')
  assert.equal(draftType([], undefined), null)
  assert.equal(groupField({ grouping_fields: [] }), '')
})

test('groups picked under an old grouping field must be picked again', () => {
  const customer = { business_doctype: 'Customer', grouping_fields: ['territory'] }
  const saved = { doctype: 'Customer', mode: GROUP, values: ['North'], groupingField: 'customer_group' }
  assert.equal(staleGroups(saved, customer), true)
  assert.deepEqual(businessRows([saved]), [{ business_doctype: 'Customer', access: GROUP, value: 'North', grouping_field: 'customer_group' }],
    'The old field goes to the server, which refuses it instead of rebinding the groups')
  assert.equal(staleGroups({ ...saved, groupingField: 'territory' }, customer), false)
  assert.equal(staleGroups({ ...saved, values: [] }, customer), false)
  assert.equal(staleGroups({ ...saved, mode: RECORD }, customer), false)
})
