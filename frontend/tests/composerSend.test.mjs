import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, ref, watch } from 'vue'
import { injectCapabilities } from './channelCapabilities.js'
import { composerKinds, defaultSendSource } from '../src/services/enabledChannels.js'
import { resetRecipient } from '../src/services/recipientContext.js'
import { sha256Hex } from '../src/services/crypto.js'
import { messageData, objectValue } from '../src/components/messageContent.js'
import { coordinates } from '../src/components/formValidation.js'

const source = (await readFile(new URL('../src/composables/useMessages.js', import.meta.url), 'utf8'))
  .replace(/^import .*\n/gm, '').replace('export function', 'function')
const make = new Function('ref', 'computed', 'watch', 'onMounted', 'onBeforeUnmount', 'useRealtimeRefresh', 'coreApi',
  'resetRecipient', 'sha256Hex', 'randomUUID', 'messageData', 'objectValue', 'coordinates', 'inject', 'composerKinds', 'defaultSendSource', source + '\nreturn useMessages();')
const deferred = () => { let resolve, reject; const promise = new Promise((done, fail) => { resolve = done; reject = fail }); return { promise, resolve, reject } }
const tick = () => new Promise(resolve => setImmediate(resolve))
const row = (name, time) => ({ name, channel: 'whatsapp', direction: 'Incoming', content: name, creation: time,
  sender_endpoint: '15550000001', provider_context: { provider: 'WhatsApp' } })
const thread = [row('RELAY-MSG-0000000001', '2026-10-28 10:00:00'), row('RELAY-MSG-0000000002', '2026-10-28 10:10:00'),
  row('RELAY-MSG-0000000003', '2026-10-28 10:20:00')]

function fixture(t, override = () => {}) {
  const memory = {}, previous = {}
  for (const key of ['document', 'window', 'sessionStorage', 'location']) previous[key] = globalThis[key]
  globalThis.document = { visibilityState: 'visible' }
  globalThis.window = { history: { pushState() {} } }
  globalThis.location = { hash: '' }
  globalThis.sessionStorage = Object.assign(memory, {
    getItem: key => memory[key], setItem: (key, value) => memory[key] = value, removeItem: key => delete memory[key],
  })
  const calls = [], scope = effectScope()
  let uuid = 0
  const api = async (method, values) => {
    calls.push({ method, values })
    const response = override(method, values)
    if (response !== undefined) return response
    if (method === 'api.conversation_channels') return { items: [{ value: 'whatsapp' }] }
    if (method.endsWith('view_state')) return {}
    if (method === 'messaging.pending_messages' || method === 'messaging.action_snapshots') return { items: [] }
    if (method === 'api.messages') return { items: thread, first: thread[0].name, last: thread.at(-1).name, ingestion_cursor: thread.at(-1).name, has_more: false }
    if (method === 'messaging.send') return { status: 'Submitted', action: 'RELAY-MA-0000000001' }
    throw Error('Unexpected method: ' + method)
  }
  const state = scope.run(() => make(ref, computed, watch, () => {}, () => {}, () => {}, api, resetRecipient, sha256Hex,
    () => 'key-' + ++uuid, messageData, objectValue, coordinates, injectCapabilities, composerKinds, defaultSendSource))
  t.after(() => { scope.stop(); for (const [key, value] of Object.entries(previous)) globalThis[key] = value })
  return { state, calls, sends: () => calls.filter(call => call.method === 'messaging.send').map(call => call.values) }
}

test('Send clears the composer and shows the pending message before the server answers', async t => {
  const response = deferred()
  const { state } = fixture(t, method => method === 'messaging.send' ? response.promise : undefined)
  await state.open('A')
  state.body.value = 'Hello'
  const send = state.send()
  assert.equal(state.body.value, '')
  assert.equal(state.displayRows.value.at(-1).content, 'Hello')
  assert.equal(state.displayRows.value.at(-1).status, 'Sending')
  response.resolve({ status: 'Submitted', action: 'RELAY-MA-0000000001' })
  await send
  assert.equal(state.displayRows.value.some(row => row._pending), false)
})

test('a rapid second Send of the same message sends it once', async t => {
  const response = deferred()
  const { state, sends } = fixture(t, method => method === 'messaging.send' ? response.promise : undefined)
  await state.open('A')
  state.body.value = 'Hello'
  const first = state.send(), second = state.send(), third = state.send(state.source.value, 'text', { text: 'Hello' })
  response.resolve({ status: 'Submitted', action: 'RELAY-MA-0000000001' })
  await Promise.all([first, second, third])
  assert.deepEqual(sends().map(values => values.data.text), ['Hello'])
})

test('a new message sent during a send goes out after it, in order', async t => {
  const responses = [deferred(), deferred()]
  const { state, sends } = fixture(t, method => method === 'messaging.send' ? responses[sends().length - 1].promise : undefined)
  await state.open('A')
  state.body.value = 'First'
  const first = state.send()
  state.body.value = 'Second'
  const second = state.send()
  assert.equal(state.body.value, '')
  await tick()
  assert.deepEqual(sends().map(values => values.data.text), ['First'])
  responses[0].resolve({ status: 'Submitted', action: 'RELAY-MA-0000000001' })
  await first
  await tick()
  responses[1].resolve({ status: 'Submitted', action: 'RELAY-MA-0000000002' })
  await second
  assert.deepEqual(sends().map(values => values.data.text), ['First', 'Second'])
})

test('a send that fails before the server accepts it puts the text back and keeps a retryable message', async t => {
  let fail = true
  const { state, sends } = fixture(t, method => {
    if (method !== 'messaging.send') return undefined
    if (fail) return Promise.reject(Error('Connection lost'))
  })
  await state.open('A')
  state.body.value = 'Hello'
  await state.send()
  assert.equal(state.body.value, 'Hello')
  assert.equal(state.error.value, 'Connection lost')
  const failed = state.displayRows.value.find(row => row._pending)
  assert.equal(failed.status, 'Unconfirmed')
  fail = false
  await state.retryPending(failed)
  assert.deepEqual(sends().map(values => values.request_key), ['key-1', 'key-1'])
  assert.equal(state.displayRows.value.some(row => row._pending), false)
})

test('a failed send does not overwrite a new draft', async t => {
  const response = deferred()
  const { state } = fixture(t, method => method === 'messaging.send' ? response.promise : undefined)
  await state.open('A')
  state.body.value = 'Hello'
  const send = state.send()
  state.body.value = 'New draft'
  response.reject(Error('Connection lost'))
  await send
  assert.equal(state.body.value, 'New draft')
})

test('a sent photo closes the attachment panel, and a failed one puts it back', async t => {
  let fail = false
  const { state } = fixture(t, method => method === 'messaging.send' && fail ? Promise.reject(Error('Connection lost')) : undefined)
  await state.open('A')
  const photo = { name: 'FILE-1', filename: 'photo.jpg', size: 10 }
  state.kind.value = 'photo'; state.attachment.value = photo
  await state.send()
  assert.equal(state.kind.value, 'text')
  assert.equal(state.attachment.value, null)
  fail = true
  state.kind.value = 'photo'; state.attachment.value = photo
  await state.send()
  assert.equal(state.kind.value, 'photo')
  assert.deepEqual(state.attachment.value, photo)
})

test('a reply sent from an older message jumps to the newest one', async t => {
  const { state } = fixture(t)
  await state.open('A')
  state.rememberPosition({ name: thread[0].name, offset: 20, atBottom: false })
  state.reply(thread[0])
  state.body.value = 'Answer'
  const send = state.send()
  assert.equal(state.viewPosition.value, null)
  await send
})

const rejected = { name: 'pending:RELAY-MA-0000000009', action: 'RELAY-MA-0000000009', scope: 'A', channel: 'whatsapp',
  provider_context: { provider: 'WhatsApp' }, direction: 'Outgoing', content: 'Not sent', creation: '2026-10-28 10:05:00',
  status: 'Failed', _pending: true }

test('a failed message sits at its own time in the thread, not at the bottom', async t => {
  const { state } = fixture(t, method => method === 'messaging.pending_messages' ? { items: [{ ...rejected }] } : undefined)
  await state.open('A')
  assert.deepEqual(state.displayRows.value.map(row => row.name),
    ['RELAY-MSG-0000000001', rejected.name, 'RELAY-MSG-0000000002', 'RELAY-MSG-0000000003'])
})

test('Delete hides a failed message on the server and in the thread', async t => {
  const { state, calls } = fixture(t, method => {
    if (method === 'messaging.pending_messages') return { items: calls.some(call => call.method === 'messaging.dismiss') ? [] : [{ ...rejected }] }
    if (method === 'messaging.dismiss') return { action: rejected.action }
  })
  await state.open('A')
  await state.deletePending(state.displayRows.value.find(row => row._pending))
  assert.deepEqual(calls.filter(call => call.method === 'messaging.dismiss').map(call => call.values), [{ action: rejected.action }])
  assert.equal(state.displayRows.value.some(row => row._pending), false)
})

test('Retry of a rejected message resends it once and leaves no duplicate', async t => {
  const { state, calls } = fixture(t, method => {
    if (method === 'messaging.pending_messages') return { items: calls.some(call => call.method === 'messaging.retry') ? [] : [{ ...rejected }] }
    if (method === 'messaging.retry') return { action: 'RELAY-MA-0000000010', status: 'Submitted' }
  })
  await state.open('A')
  await state.retryPending(state.displayRows.value.find(row => row._pending))
  assert.deepEqual(calls.filter(call => call.method === 'messaging.retry').map(call => call.values), [{ action: rejected.action }])
  assert.equal(state.displayRows.value.some(row => row._pending), false)
})
