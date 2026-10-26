import test from 'node:test'
import { injectCapabilities } from './channelCapabilities.js'
import { composerKinds, defaultSendSource } from '../src/services/enabledChannels.js'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, ref, watch } from 'vue'
import { resetRecipient } from '../src/services/recipientContext.js'
import { sha256Hex } from '../src/services/crypto.js'
import { messageData, objectValue } from '../src/components/messageContent.js'
import { coordinates } from '../src/components/formValidation.js'

const source = (await readFile(new URL('../src/composables/useMessages.js', import.meta.url), 'utf8'))
  .replace(/^import .*\n/gm, '').replace('export function', 'function')
const make = new Function('ref', 'computed', 'watch', 'onMounted', 'onBeforeUnmount', 'useRealtimeRefresh', 'coreApi',
  'resetRecipient', 'sha256Hex', 'randomUUID', 'messageData', 'objectValue', 'coordinates', 'inject', 'composerKinds', 'defaultSendSource', source + '\nreturn useMessages();')
const name = index => 'RELAY-MSG-' + String(index).padStart(10, '0')
const thread = Array.from({ length: 30 }, (_, index) => ({ name: name(index + 1), channel: 'whatsapp', direction: 'Incoming',
  content: 'Message ' + (index + 1), creation: name(index + 1), provider_context: { provider: 'WhatsApp' } }))

function fixture(t, viewState) {
  const previous = {}
  for (const key of ['document', 'window', 'sessionStorage', 'location']) previous[key] = globalThis[key]
  globalThis.document = { visibilityState: 'visible' }
  globalThis.window = { history: { pushState() {} } }
  globalThis.location = { hash: '' }
  globalThis.sessionStorage = { getItem() {}, setItem() {}, removeItem() {} }
  const calls = [], scope = effectScope()
  const api = async (method, values) => {
    calls.push({ method, values })
    if (method === 'api.conversation_channels') return { items: [{ value: 'whatsapp' }] }
    if (method === 'inbox.view_state') return viewState(values.contact)
    if (method === 'messaging.pending_messages') return { items: [] }
    if (method === 'api.messages') {
      const items = thread.slice(-(values.limit || 50))
      return { items, first: items[0].name, last: items.at(-1).name, ingestion_cursor: thread.at(-1).name, has_more: false }
    }
    if (method === 'api.message_context') {
      const index = thread.findIndex(row => row.name === values.message), items = thread.slice(Math.max(0, index - 25), index + 26)
      return { items, first: items[0].name, last: items.at(-1).name, has_more: index > 25, has_newer: index + 26 < thread.length }
    }
    throw Error('Unexpected method: ' + method)
  }
  const state = scope.run(() => make(ref, computed, watch, () => {}, () => {}, () => {}, api, resetRecipient, sha256Hex,
    () => 'key', messageData, objectValue, coordinates, injectCapabilities, composerKinds, defaultSendSource))
  t.after(() => { scope.stop(); for (const [key, value] of Object.entries(previous)) globalThis[key] = value })
  return { state, calls }
}

// Live data: the saved reading position was the oldest message, left there by an earlier scroll up.
const stale = { channel: '', name: name(1), offset: 62.5, atBottom: false }

test('a conversation with unread messages opens at the first unread one, not at a stale saved position', async t => {
  const { state, calls } = fixture(t, () => ({ ...stale, first_unread: name(26) }))
  await state.open('RELAY-CON-0000000001')
  assert.deepEqual(calls.filter(call => call.method === 'api.message_context').map(call => call.values.message), [name(26)])
  assert.equal(state.restored.value, name(26))
  assert.equal(state.firstUnread.value, name(26))
  assert.deepEqual(state.viewPosition.value, { name: name(26), offset: 56, atBottom: false })
  assert.equal(state.rows.value.at(-1).name, name(30))
})

test('a read conversation opens at the newest message even with a saved position higher up', async t => {
  const { state, calls } = fixture(t, () => ({ ...stale, first_unread: null }))
  await state.open('RELAY-CON-0000000001')
  assert.equal(calls.some(call => call.method === 'api.message_context'), false)
  assert.equal(state.restored.value, '')
  assert.equal(state.firstUnread.value, '')
  assert.equal(state.viewPosition.value, null)
  assert.equal(state.rows.value.at(-1).name, name(30))
})

test('returning to a conversation applies the rule again instead of a cached scroll position', async t => {
  let unread = null
  const { state, calls } = fixture(t, () => ({ channel: '', first_unread: unread }))
  await state.open('RELAY-CON-0000000001')
  state.rememberPosition({ name: name(5), offset: 0, atBottom: false })
  await state.open('RELAY-CON-0000000002')
  unread = name(29)
  await state.open('RELAY-CON-0000000001')
  assert.equal(calls.filter(call => call.method === 'inbox.view_state').length, 3)
  assert.equal(state.restored.value, name(29))
})
