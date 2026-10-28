import test from 'node:test'
import assert from 'node:assert/strict'
import { choicesText, cleanStep, flowValues, hasUnpublished, moveStep, newFlow, newStep, nextLabel, parseChoices, removeStep, renameStep, triggerSummary } from '../src/services/flowEditor.js'

test('new steps get unique ids and the fields their kind needs', () => {
  const steps = [newStep('input', [])]
  steps.push(newStep('input', steps))
  assert.notEqual(steps[0].id, steps[1].id)
  assert.notEqual(steps[0].variable, steps[1].variable)
  assert.deepEqual(newStep('condition', steps), { id: 'condition_3', kind: 'condition', text: '', variable: '', operator: 'eq', value: '', then: '', otherwise: '' })
  assert.equal(newFlow().nodes.length, 1)
})

test('choices round-trip between lines and label/value pairs', () => {
  const choices = parseChoices('Create Ticket = create\n\n View Ticket \nA=b=c')
  assert.deepEqual(choices, [{ label: 'Create Ticket', value: 'create' }, { label: 'View Ticket', value: 'View Ticket' }, { label: 'A', value: 'b=c' }])
  assert.equal(choicesText(choices), 'Create Ticket = create\nView Ticket\nA = b=c')
  assert.equal(choicesText(['Yes']), 'Yes')
})

test('saved steps drop empty and unrelated fields and keep numbers as numbers', () => {
  assert.deepEqual(cleanStep({ id: 'a', kind: 'input', text: 'Name?', variable: 'name', input_type: 'text', next: '', max_length: '140', min_length: '', choices: [], optional: false, accept: ['text'] }),
    { id: 'a', kind: 'input', text: 'Name?', variable: 'name', input_type: 'text', max_length: 140 })
  assert.deepEqual(cleanStep({ id: 'e', kind: 'end', text: 'Bye', next: 'a' }), { id: 'e', kind: 'end', text: 'Bye' })
  assert.deepEqual(cleanStep({ id: 'w', kind: 'wait', text: '', seconds: '30' }), { id: 'w', kind: 'wait', text: '', seconds: 30 })
  assert.deepEqual(cleanStep({ id: 'x', kind: 'action', text: '', action: 'a.b', arguments: {}, variable: '' }), { id: 'x', kind: 'action', text: '', action: 'a.b', arguments: {} })
})

test('moving, renaming and removing keep links consistent', () => {
  const steps = [{ id: 'a', kind: 'input' }, { id: 'b', kind: 'condition', then: 'c', otherwise: 'a' }, { id: 'c', kind: 'end' }]
  renameStep(steps, steps[0], 'ask')
  assert.equal(steps[1].otherwise, 'ask')
  removeStep(steps, 2)
  assert.equal(steps[1].then, '')
  moveStep(steps, 1, -1)
  assert.deepEqual(steps.map(step => step.id), ['b', 'ask'])
  moveStep(steps, 0, -1)
  assert.deepEqual(steps.map(step => step.id), ['b', 'ask'])
})

test('summaries describe triggers, routing and unpublished drafts', () => {
  assert.equal(triggerSummary({ command: '/help', keywords: 'help me\nsupport', template_button: 'x' }), '/help · “help me” · “support” · Template button')
  assert.equal(triggerSummary({}), 'No trigger')
  const steps = [{ id: 'a', kind: 'input' }, { id: 'b', kind: 'reply', next: 'a' }, { id: 'c', kind: 'end' }]
  assert.deepEqual(steps.map((_, index) => nextLabel(steps, index)), ['Then b', 'Then a', 'Flow ends'])
  assert.equal(hasUnpublished({ nodes: '[1]', published_nodes: '[1]' }), false)
  assert.equal(hasUnpublished({ nodes: '[1]', published_nodes: null }), true)
  assert.deepEqual(Object.keys(flowValues(newFlow())), ['title', 'command', 'keywords', 'template_button', 'channel', 'execution_user', 'business_doctype', 'nodes'])
})

test('the Flows page needs the flows capability, which the backend gives only while Enable flows is on', async () => {
  const { navAllowed } = await import('../src/services/navigation.js')
  const { readFile } = await import('node:fs/promises')
  const app = await readFile(new URL('../src/SiteApp.vue', import.meta.url), 'utf8')
  assert.match(app, /name: 'Flows'[^}]*flows: true/)
  assert.equal(navAllowed({ name: 'Flows', flows: true }, { manage: true, flows: false }), false)
  assert.equal(navAllowed({ name: 'Flows', flows: true }, { manage: true, flows: true }), true)
})

test('editor-only fields never reach the server', () => {
  const step = { id: 'act', kind: 'action', action: 'x', arguments: { a: 1 }, _arguments: '{"a": 1}' }
  assert.deepEqual(cleanStep(step), { id: 'act', kind: 'action', action: 'x', arguments: { a: 1 } })
})

test('a loaded flow with editor fields still matches its published steps', () => {
  const published = JSON.stringify([{ kind: 'action', id: 'act', text: '', action: 'x', arguments: { a: 1 } }])
  const nodes = [{ id: 'act', kind: 'action', action: 'x', text: '', arguments: { a: 1 }, _arguments: '{"a": 1}' }]
  assert.equal(hasUnpublished({ nodes, published_nodes: published }), false)
  nodes[0].action = 'y'
  assert.equal(hasUnpublished({ nodes, published_nodes: published }), true)
})

test('publication compares channel, actor, business and every trigger setting', () => {
  const settings = { channel: 'channel', execution_user: 'manager', business_doctype: 'Customer', command: '/help', keywords: 'support', template_button: 'start' }
  const flow = { ...settings, nodes: '[1]', published_nodes: '[1]', published_settings: settings }
  assert.equal(hasUnpublished(flow), false)
  for (const key of Object.keys(settings)) assert.equal(hasUnpublished({ ...flow, [key]: 'changed' }), true, key)
})

test('AI and assignment nodes keep configuration and stopping AI is terminal', () => {
  assert.equal(newStep('ai_skill', []).on_reply, 'Continue')
  assert.equal(newStep('assign', []).team, '')
  const node = { ...newStep('ai_skill', []), ai_skill: 'Support', on_reply: 'Stop', next: 'later' }
  assert.equal(cleanStep(node).next, undefined)
  assert.equal(nextLabel([node], 0), 'Flow ends')
})
