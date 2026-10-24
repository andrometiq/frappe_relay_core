import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, nextTick, ref, watch } from 'vue'
import { resetRecipient } from '../src/services/recipientContext.js'
import { sha256Hex } from '../src/services/crypto.js'
import { messageData, objectValue } from '../src/components/messageContent.js'
import { coordinates } from '../src/components/formValidation.js'

const source = (await readFile(new URL('../src/composables/useMessages.js', import.meta.url), 'utf8'))
  .replace(/^import .*\n/gm, '').replace('export function', 'function')
const make = new Function('ref', 'computed', 'watch', 'onMounted', 'onBeforeUnmount', 'useRealtimeRefresh', 'coreApi',
  'resetRecipient', 'sha256Hex', 'randomUUID', 'messageData', 'objectValue', 'coordinates', source + '\nreturn useMessages();')
const deferred = () => { let resolve; const promise = new Promise(done => resolve = done); return { promise, resolve } }
const tick = () => new Promise(resolve => setImmediate(resolve))
function fixture(t, override = () => {}) {
  const memory = {}, previous = {}
  for (const key of ['document', 'window', 'sessionStorage', 'location']) previous[key] = globalThis[key]
  globalThis.document = {visibilityState:'visible'}
  globalThis.window = {history:{pushState() {}}}
  globalThis.location = {hash:''}
  globalThis.sessionStorage = Object.assign(memory, {
    getItem:key => memory[key], setItem:(key, value) => memory[key] = value, removeItem:key => delete memory[key],
  })
  const calls = [], records = new Map(), scope = effectScope()
  let realtime, uuid = 0
  const row = (name, channel = 'telegram') => ({name, channel, content:'Order 25', status:'Sent',
    creation:name, sender_endpoint:'local-only', provider_context:{provider:'Telegram'}})
  const api = async (method, values) => {
    calls.push({method, values})
    const response = override(method, values)
    if (response !== undefined) return response
    if (method === 'api.conversation_channels') return {items:[{value:'telegram'}, {value:'whatsapp'}]}
    if (method === 'business_inbox.context') return {name:values.name}
    if (method.endsWith('view_state')) return {}
    if (method === 'messaging.pending_messages' || method === 'messaging.action_snapshots') return {items:[]}
    if (['api.messages', 'business_inbox.messages', 'api.message_snapshots'].includes(method)) {
      const key = values.contact || values.doctype + ':' + values.name
      const all = records.get(key) || [row(key + '-1')]
      const items = all.filter(item => (!values.channel || item.channel === values.channel)
        && (!values.since || item.name > values.since) && (!values.names || JSON.parse(values.names).includes(item.name)))
      return {items, first:items[0]?.name, last:items.at(-1)?.name, ingestion_cursor:all.at(-1)?.name, has_more:false}
    }
    if (method === 'messaging.send') return {status:'Submitted', action:'action'}
    throw Error('Unexpected method: ' + method)
  }
  const state = scope.run(() => make(ref, computed, watch, () => {}, () => {}, (_rooms, _kinds, fn) => realtime = fn,
    api, resetRecipient, sha256Hex, () => 'key-' + ++uuid, messageData, objectValue, coordinates))
  t.after(() => { scope.stop(); for (const [key, value] of Object.entries(previous)) globalThis[key] = value })
  return {state, calls, records, row, realtime:(kind) => realtime({kinds:new Set([kind])})}
}

for (const status of ['Submitted', 'Queued']) test(`${status} preserves edits made during send and clears unchanged fields`, async t => {
  const response = deferred()
  const {state, row} = fixture(t, method => method === 'messaging.send' ? response.promise : undefined)
  await state.open('A')
  state.body.value = 'First draft'; state.attachment.value = {name:'first-file'}; state.quoting.value = true
  const send = state.send()
  assert.equal(state.busy.value, true)
  state.body.value = 'Follow-up draft'; state.attachment.value = {name:'second-file'}; state.source.value = row('other-quote')
  response.resolve({status, action:'action'})
  await send
  assert.equal(state.body.value, 'Follow-up draft')
  assert.equal(state.attachment.value.name, 'second-file')
  assert.equal(state.quoting.value, true)
  await state.send()
  assert.equal(state.body.value, '')
  assert.equal(state.attachment.value, null)
  assert.equal(state.quoting.value, false)
})

test('reaction and a changed business scope preserve the composer', async t => {
  const response = deferred()
  const {state} = fixture(t, method => method === 'messaging.send' ? response.promise : undefined)
  await state.open('A'); state.body.value = 'Draft'; state.quoting.value = true
  const send = state.send(state.source.value, 'reaction', {emoji:'👍'})
  response.resolve({status:'Submitted', action:'action'}); await send
  assert.equal(state.body.value, 'Draft'); assert.equal(state.quoting.value, true)
  const again = state.send(); state.businessType.value = 'Supplier'; state.businessName.value = 'B'
  await again
  assert.equal(state.body.value, 'Draft')
})

test('cached contact and channel restores catch up messages and statuses without polling', async t => {
  const {state, records, row, calls} = fixture(t)
  records.set('A', [row('A-1'), row('A-2', 'whatsapp')])
  await state.open('A'); await state.open('B')
  records.set('A', [{...row('A-1'), status:'Read'}, row('A-2', 'whatsapp'), row('A-3')])
  await state.open('A')
  assert.equal(state.rows.value.find(item => item.name === 'A-1').status, 'Read')
  assert.equal(state.rows.value.at(-1).name, 'A-3')
  await state.filterChannel('telegram'); await state.filterChannel('whatsapp')
  records.get('A').push(row('A-4'))
  await state.filterChannel('telegram')
  assert.equal(state.rows.value.at(-1).name, 'A-4')
  assert.ok(calls.some(call => call.method === 'api.messages' && call.values.since === 'A-3' && call.values.channel === 'telegram'))
})

test('business cache keys separate Customer and Supplier and denied restores expose no cached data', async t => {
  let denied = false
  const {state, records, row} = fixture(t, (method, values) => {
    if (denied && method === 'business_inbox.context' && values.doctype === 'Customer') return Promise.reject(Object.assign(Error('Denied'), {status:403}))
  })
  records.set('Customer:shared', [row('C-1')]); records.set('Supplier:shared', [row('S-1')])
  await state.openBusiness('Customer', 'shared', false)
  await state.openBusiness('Supplier', 'shared', false)
  records.get('Customer:shared').push(row('C-2'))
  await state.openBusiness('Customer', 'shared', false)
  assert.deepEqual(state.rows.value.map(item => item.name), ['C-1', 'C-2'])
  await state.openBusiness('Supplier', 'shared', false); denied = true
  await state.openBusiness('Customer', 'shared', false)
  assert.deepEqual(state.rows.value, []); assert.equal(state.error.value, 'Denied')
})

test('a cached restore catches up after an old scope refresh finishes', async t => {
  const delayed = deferred(); let hold = false
  const {state, records, row, realtime} = fixture(t, (method, values) => {
    if (hold && method === 'api.messages' && values.contact === 'B' && values.since) return delayed.promise
  })
  await state.open('A'); await state.open('B'); hold = true
  const refresh = realtime('messages')
  records.set('A', [row('A-1'), row('A-2')])
  await state.open('A')
  delayed.resolve({items:[row('B-2')], ingestion_cursor:'B-2', has_more:false})
  await refresh; await tick(); await nextTick()
  assert.deepEqual(state.rows.value.map(item => item.name), ['A-1', 'A-2'])
})
