import test from 'node:test'
import assert from 'node:assert/strict'
import { configurationValues, newConfiguration, toolRows, variantPreview } from '../src/services/automationEditor.js'

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

test('rule cards describe document, recipient and lifecycle in plain words', async () => {
  const { eventDescription } = await import('../src/services/automationEditor.js')
  assert.equal(eventDescription({ source_doctype: 'Delivery Note', business_doctype: 'Customer', event: 'on_submit' }), 'Delivery Note → Customer · on submit')
  assert.match(eventDescription({ event: 'after_insert' }), /when created/)
})
test('message preview replaces numbered parameters in order and preserves missing slots', async () => {
  const { messagePreview, toolCount } = await import('../src/services/automationEditor.js')
  assert.equal(messagePreview('Order {{1}}: {{ 2 }}. {{3}}', 'name\nitems_summary'), 'Order [name]: [items_summary]. [Parameter 3]')
  assert.equal(messagePreview('Plain wording', ''), 'Plain wording')
  assert.equal(toolCount('invalid'), 0)
  assert.equal(toolCount('[{},{}]'), 2)
})

test('event edits preserve consent selection and channel variants',()=>{
  const draft={...newConfiguration(false),use_preferences:true,contact:'person',telegram_body:'Order {name}',email_subject:'Order {name}',email_body:'Quantity {total_qty}',email_signature:'Regards'}
  const values=configurationValues(draft,false,[],'name\ntotal_qty')
  assert.equal(values.use_preferences,1);assert.equal(values.email_body,draft.email_body);assert.equal(values.contact,'person')
  assert.equal(variantPreview('Order {name}: {secret}', 'name'),'Order [name]: [Undeclared: secret]')
})
