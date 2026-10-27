import test from 'node:test'
import assert from 'node:assert/strict'
import { configurationChannels, configurationValues, newConfiguration, toolRows, variantPreview } from '../src/services/automationEditor.js'

test('new skills and event rules are disabled; skills start in shadow', () => {
  assert.equal(newConfiguration(true).mode, 'Shadow')
  for (const skill of [true, false]) assert.equal(newConfiguration(skill).enabled, 0)
})
test('skill saves only editable configuration and preserves explicit read scope', () => {
  const draft = { ...newConfiguration(true), name: 'SKILL-1', owner: 'other', daily_limit: '25', enabled: true }
  const tools = [{ name: 'ledger', method: 'get_list', doctype: 'Payment Ledger Entry', fields: ['name', 'amount', 'posting_date'], scope_field: 'party', identity_fields: {} }]
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


test('channel options retain an existing selection outside the current account without duplicates', () => {
  const available = [{ name: 'current', channel: 'Email', title: 'Sales mailbox' }]
  assert.deepEqual(configurationChannels(available, 'saved'), [...available, {name: 'saved'}])
  assert.deepEqual(configurationChannels(available, 'current'), available)
  assert.deepEqual(configurationChannels(available, ''), available)
  assert.deepEqual(configurationChannels([], 'saved'), [{name: 'saved'}])
  assert.equal(available.length, 1)
})

test('event text and identity contracts survive round trips without changing provider mappings', () => {
  const draft = {...newConfiguration(true), target:'Explain my ledger', instructions:'Only my records', reply_style:'Brief', exact_trigger:'/ledger', search_confirmation:'Always', execution_policy:'Execute'}
  const tools = [{name:'ledger',method:'get_list',doctype:'GL Entry',fields:['debit','credit'],scope_field:'party',identity_anchor:'Supplier',identity_fields:{WhatsApp:'phone',Email:'email'},company_field:'company'}]
  const actions = [{action:'create_draft',doctype:'Payment Entry',fields:['paid_amount']},{action:'reply'}]
  const values = configurationValues(draft,true,tools,'',actions)
  assert.deepEqual(toolRows(values.allowed_tools),tools)
  assert.deepEqual(JSON.parse(values.allowed_actions),actions)
  for (const key of ['target','instructions','reply_style','exact_trigger','search_confirmation','execution_policy']) assert.equal(values[key],draft[key])
  draft.execution_policy='Ticket only'
  assert.deepEqual(JSON.parse(configurationValues(draft,true,tools,'',actions).allowed_actions),[])
})
test('ordered actions can move only inside the sequence', async () => {
  const {moveAction} = await import('../src/services/automationEditor.js')
  const actions=[{action:'create_draft'},{action:'reply'}]
  moveAction(actions,0,-1);assert.equal(actions[0].action,'create_draft')
  moveAction(actions,1,-1);assert.equal(actions[0].action,'reply')
  moveAction(actions,1,1);assert.equal(actions[1].action,'create_draft')
})
test('save validation requires complete sender and company scope and bounded owner text', async () => {
  const {eventErrors} = await import('../src/services/automationEditor.js')
  const draft={...newConfiguration(true),title:'Ledger',business_doctype:'Supplier',instructions:'Only this sender'}
  assert.deepEqual(eventErrors(draft,[],[],'Email'),[])
  assert.ok(eventErrors({...draft,enabled:1},[],[],'Email').length)
  assert.ok(eventErrors({...draft,reply_style:'x'.repeat(2001)},[],[],'Email').length)
  const reference={name:'ledger',doctype:'GL Entry',fields:['debit'],scope_field:'party',identity_anchor:'Supplier',identity_fields:{Email:'alias'},company_field:'company'}
  assert.deepEqual(eventErrors(draft,[reference],[],'Email'),[])
  assert.ok(eventErrors(draft,[reference],[],'WhatsApp').length)
  assert.ok(eventErrors({...draft,business_doctype:'Customer'},[reference],[],'Email').length)
  assert.ok(eventErrors(draft,[reference,reference],[],'Email').length)
})
test('the template picker searches by name on the chosen number and keeps the saved label', async () => {
  const { newConfiguration, templateField } = await import('../src/services/automationEditor.js')
  const fixed = templateField({ ...newConfiguration(false), channel: 'CH-1', enabled: 1, template: 'abc123' }, false, 'order_ready')
  assert.equal(fixed.method, 'business_events.template_options')
  assert.deepEqual(fixed.params, { channel: 'CH-1' })
  assert.equal(fixed.required, true)
  assert.deepEqual(fixed.initialOptions, [{ value: 'abc123', label: 'order_ready' }])
  const preferred = templateField({ ...newConfiguration(false), channel: 'CH-1', use_preferences: 1 }, true, '')
  assert.deepEqual(preferred.params, {})
  assert.equal(preferred.required, false); assert.equal(preferred.readOnly, true)
  assert.deepEqual(preferred.initialOptions, [])
})
