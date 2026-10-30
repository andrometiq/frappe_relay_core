import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { channelValues, channelLabel, displayedSteps, newChannelStep, STEP_TYPES } from '../src/services/channelAutomation.js'
import { moveStep } from '../src/services/flowEditor.js'
import { navAllowed, railGroups } from '../src/services/navigation.js'

test('channel steps preserve order and explicit continuation across save', () => {
  const steps = STEP_TYPES.map(newChannelStep)
  moveStep(steps, 4, -1)
  const values = channelValues({ automation_enabled: true, steps, timezone: 'Asia/Kolkata', open_time: '09:00', close_time: '18:00', working_days: 'Monday' })
  assert.deepEqual(values.steps.map(row => row.step), ['Flow', 'AI skill', 'Assign', 'Out of hours reply', 'Ticket'])
  assert.equal(values.steps[2].on_reply, 'Continue')
  assert.equal(values.steps[0].on_reply, 'Stop')
  assert.equal(values.automation_enabled, 1)
  assert.equal(channelValues({ steps: [], automation_enabled: false }).automation_enabled, 0)
})

test('channel automation is a manager page in Automation independent of AI switch', () => {
  const page = { name: 'Channel automation', manage: true }
  assert.equal(navAllowed(page, { manage: true, ai: false }), true)
  assert.equal(navAllowed(page, { manage: false, ai: true }), false)
  assert.deepEqual(railGroups([page])[0].pages, [page])
})

test('screen preserves dirty edits on socket refresh and previews only saved settings', async () => {
  const screen = await readFile(new URL('../src/components/ChannelAutomation.vue', import.meta.url), 'utf8')
  assert.match(screen, /useRealtimeRefresh\(\['Relay Channel'\]/)
  assert.match(screen, /if \(dirty.value\) stale.value = true/)
  assert.match(screen, /busy \|\| dirty \|\| !text.trim\(\)/)
  assert.doesNotMatch(screen, /setInterval|setTimeout/)
  for (const action of ['Add step', 'Move step', 'Remove step', 'Test message']) assert.ok(screen.includes(action))
})


test('default cards show the runtime defaults without silently saving them', () => {
  const draft = { steps: [], defaults: [{ step: 'Flow', enabled: 1, on_reply: 'Stop' }, { step: 'AI skill', enabled: 1, on_reply: 'Stop' }] }
  const shown = displayedSteps(draft)
  assert.deepEqual(shown.map(row => row.step), ['Flow', 'AI skill'])
  shown[0].enabled = 0
  assert.equal(draft.defaults[0].enabled, 1)
  assert.deepEqual(channelValues(draft).steps, [])
  draft.steps = shown
  assert.equal(channelValues(draft).steps[0].enabled, 0)
})

test('selected channels retain the same distinct labels as their search results', () => {
  assert.equal(channelLabel({ name: 'wa', title: 'yrp', channel: 'WhatsApp', address: '+91 98000 00001' }), 'WhatsApp · yrp · +91 98000 00001')
  assert.equal(channelLabel({ name: 'mail', title: 'yrp', channel: 'Email', address: 'help@example.invalid' }), 'Email · yrp · help@example.invalid')
})
