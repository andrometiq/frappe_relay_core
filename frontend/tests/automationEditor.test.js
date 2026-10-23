import test from 'node:test'
import assert from 'node:assert/strict'
import { configurationValues, newConfiguration, toolRows } from '../src/services/automationEditor.js'

test('new skills and event rules are disabled; skills start in shadow', () => {
  assert.equal(newConfiguration(true).mode, 'Shadow')
  for (const skill of [true, false]) assert.equal(newConfiguration(skill).enabled, 0)
})
test('skill saves only editable configuration and preserves explicit read scope', () => {
  const draft = { ...newConfiguration(true), name: 'SKILL-1', owner: 'other', daily_limit: '25', enabled: true }
  const tools = [{ name: 'ledger', method: 'get_list', doctype: 'Payment Ledger Entry', fields: 'name, amount, posting_date', scope_field: 'party' }]
  const result = configurationValues(draft, true, tools, '')
  assert.equal(result.owner, undefined); assert.equal(result.name, undefined)
  assert.equal(result.daily_limit, 25); assert.equal(result.enabled, 1)
  assert.deepEqual(toolRows(result.allowed_tools), tools)
})
test('event parameter order preserves template numbering', () => {
  const result = configurationValues(newConfiguration(false), false, [], 'name\n items_summary \n')
  assert.deepEqual(JSON.parse(result.parameter_mapping), ['name', 'items_summary'])
})
