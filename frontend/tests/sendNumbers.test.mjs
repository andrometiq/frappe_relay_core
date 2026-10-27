import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, nextTick, ref, watch } from 'vue'
import { objectValue } from '../src/components/messageContent.js'
import { effectiveNumber, hasManyNumbers, sendNumberChoice } from '../src/services/whatsappNumbers.js'

const source = (await readFile(new URL('../src/composables/useSendNumbers.js', import.meta.url), 'utf8'))
  .replace(/^import .*$/gm, '').replace(/^export /gm, '')
const make = new Function('computed', 'ref', 'watch', 'coreApi', 'objectValue', 'effectiveNumber', 'hasManyNumbers', 'sendNumberChoice',
  'useRealtimeRefresh', source + '\nreturn useSendNumbers;')

const capabilities = ref({ whatsapp_numbers: [{ name: 'WA-1', label: 'Sales line' }, { name: 'WA-2', label: 'Support line' }] })
const item = (channel, open) => ({ channel, label: channel, address: '', has_chat: true, window: { open, remaining_seconds: open ? 3600 : 0 } })

function setup(responses) {
  const calls = []
  let refresh
  const api = async (method, args) => { calls.push([method, args]); return responses.shift() }
  const message = { name: 'M1', channel: 'WA-1', relay_contact: 'C1', provider_context: { provider: 'WhatsApp' } }
  const state = { source: ref(message), selected: ref('C1'), quoting: ref(false), pinnedSource: ref(null), viaNumber: ref('') }
  state.pickNumber = value => { state.viaNumber.value = value }
  const numbers = make(computed, ref, watch, api, objectValue, effectiveNumber, hasManyNumbers, sendNumberChoice,
    (rooms, kinds, fn) => { assert.deepEqual(kinds, ['messages']); refresh = fn })(state, capabilities)
  return { calls, numbers, state, refresh: () => refresh() }
}
const settle = async () => { await new Promise(resolve => setImmediate(resolve)); await nextTick() }

test('a new incoming message moves the default number through the socket refresh, without polling', async () => {
  const fixture = setup([{ default: 'WA-1', items: [item('WA-1', true), item('WA-2', false)] },
    { default: 'WA-2', items: [item('WA-1', true), item('WA-2', true)] }])
  await settle()
  assert.equal(fixture.numbers.active.value, true)
  assert.equal(fixture.numbers.current.value, 'WA-1')
  assert.equal(fixture.numbers.wroteTo.value.channel, 'WA-1')
  await fixture.refresh()
  assert.equal(fixture.numbers.current.value, 'WA-2')
  assert.equal(fixture.numbers.chosen.value.window.open, true)
  assert.deepEqual(fixture.calls.map(([method, args]) => [method, args.contact]), [['messaging.send_numbers', 'C1'], ['messaging.send_numbers', 'C1']])
})

test('a staff pick wins over the default and a quote keeps its own number', async () => {
  const fixture = setup([{ default: 'WA-1', items: [item('WA-1', true), item('WA-2', false)] }])
  await settle()
  fixture.numbers.pick('WA-2')
  assert.equal(fixture.numbers.current.value, 'WA-2')
  assert.equal(fixture.numbers.choices.value[1].status, 'Window closed · template only')
  fixture.state.quoting.value = true
  assert.equal(fixture.numbers.current.value, 'WA-1')
})

test('a one-number site never asks for numbers', async () => {
  const saved = capabilities.value
  capabilities.value = { whatsapp_numbers: [{ name: 'WA-1', label: 'Sales line' }] }
  try {
    const fixture = setup([])
    await settle()
    assert.deepEqual(fixture.calls, [])
    assert.equal(fixture.numbers.active.value, false)
  } finally { capabilities.value = saved }
})
