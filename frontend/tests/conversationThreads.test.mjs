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
import { contactThread, endpointLabel, newestThread, openingThread, replyLock, replyLockText, rowChannels, sourceThread, threadAddress, threadMatches, threadTabs, waitingLabel } from '../src/services/conversationThreads.js'

const read = path => readFile(new URL('../src/' + path, import.meta.url), 'utf8')
const thread = (key, values = {}) => ({ key, relay_contact: 'RELAY-CON-1', contact_label: 'Ravi', frappe_contact: 'Ravi', channel: 'CH-SALES',
  provider: 'WhatsApp', channel_label: 'Sales', channel_address: '917000000001', endpoint: '919000000001', unread: 0, last_message: 'RELAY-MSG-01', ...values })

test('a record opens on the routed thread, else the newest unread one, else the newest one', () => {
  const sales = thread('sales', { last_message: 'RELAY-MSG-09' })
  const support = thread('support', { channel: 'CH-SUPPORT', unread: 2, last_message: 'RELAY-MSG-05' })
  const mail = thread('mail', { provider: 'Email', channel: 'CH-MAIL', endpoint: 'ravi@example.invalid', unread: 1, last_message: 'RELAY-MSG-07' })
  assert.equal(openingThread([sales, support, mail]).key, 'mail', 'The thread with the newest unread message wins over a newer read one')
  assert.equal(openingThread([sales, support, mail], 'support').key, 'support')
  assert.equal(openingThread([sales, support, mail], 'gone').key, 'mail', 'A stale routed key falls back')
  assert.equal(openingThread([sales]).key, 'sales')
  assert.equal(openingThread([]), null)
  assert.equal(newestThread([support, sales]).key, 'sales')
  assert.equal(contactThread([sales, { ...mail, frappe_contact: 'Priya' }], 'Priya').key, 'mail')
})

test('the same endpoint on another of our numbers is another thread', () => {
  const sales = thread('sales')
  assert.equal(threadMatches(sales, 'CH-SALES', '919000000001'), true)
  assert.equal(threadMatches(sales, 'CH-SUPPORT', '919000000001'), false)
  assert.equal(threadMatches(sales, 'CH-SALES', '919000000002'), false)
  assert.equal(threadMatches({ ...sales, endpoint: '' }, 'CH-SALES', ''), true)
})

test('the reply lock names the channel, the contact endpoint and our channel', () => {
  assert.equal(replyLockText(thread('sales')), 'Replying on WhatsApp to +91 90000 00001 from Sales · +91 70000 00001')
  const mail = thread('mail', { provider: 'Email', channel_label: 'Sales mail', channel_address: 'sales@example.invalid', endpoint: 'ravi@example.invalid' })
  assert.deepEqual(replyLock(mail), { icon: 'mail', verb: 'Replying by', provider: 'Email', to: 'ravi@example.invalid',
    from: 'Sales mail · sales@example.invalid', note: 'subject kept' })
  assert.equal(replyLock(null), null)
  const fromMessage = sourceThread({ relay_contact: 'RELAY-CON-1', channel: 'CH-TG', sender_endpoint: '5501', channel_title: 'Bot', provider_context: '{"provider":"Telegram"}' })
  assert.equal(replyLockText(fromMessage), 'Replying on Telegram to 5501 from Bot')
})

test('tabs name our channel only when the record talks on two of our channels of that kind', () => {
  const tabs = threadTabs([thread('sales'), thread('support', { channel: 'CH-SUPPORT', channel_label: 'Support', endpoint: '918000005678' }),
    thread('bot', { provider: 'Telegram', channel: 'CH-BOT', channel_label: 'Bot', endpoint: '55012345' }),
    thread('priya', { relay_contact: 'RELAY-CON-2', contact_label: 'Priya', provider: 'Email', channel: 'CH-MAIL', endpoint: 'priya@example.invalid' })])
  assert.deepEqual(tabs.map(tab => [tab.provider, tab.endpoint, tab.via, tab.person]), [
    ['WhatsApp', '+91 90000 00001', 'Sales', 'Ravi'], ['WhatsApp', '+91 80000 05678', 'Support', 'Ravi'],
    ['Telegram', '55012345', '', 'Ravi'], ['Email', 'priya@example.invalid', '', 'Priya']])
  assert.equal(endpointLabel('55012345', 'Telegram'), '55012345', 'A Telegram chat id is not a phone number')
})

test('a Telegram thread reads by its handle and every tab keeps its full text in the tooltip', () => {
  const bot = thread('bot', { provider: 'Telegram', channel: 'CH-BOT', channel_label: 'Bot', channel_address: '@essdee_bot', endpoint: '55012345', handle: '@ravitex' })
  assert.equal(threadAddress(bot), '@ravitex')
  assert.equal(threadAddress({ ...bot, handle: '' }), '55012345')
  assert.equal(replyLockText(bot), 'Replying on Telegram to @ravitex from Bot · @essdee_bot')
  const long = thread('mail', { provider: 'Email', channel: 'CH-MAIL', channel_label: 'Sales mail', channel_address: 'sales@example.invalid',
    endpoint: 'accounts.receivable.department.tiruppur.division@ravitextiles-international-exports.invalid' })
  assert.equal(threadTabs([long])[0].title,
    'Email · accounts.receivable.department.tiruppur.division@ravitextiles-international-exports.invalid · to our Sales mail · sales@example.invalid')
})

test('a long address ends in an ellipsis inside its tab, and edge fades follow scrolling, not a timer', async () => {
  const tabs = await read('components/messages/ThreadTabs.vue')
  assert.match(tabs, /\.thread-tab-endpoint, \.thread-tab-person, \.thread-tab-via \{ min-width:0; max-width:104px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; \}/)
  assert.match(tabs, /\.thread-tab-via \{ display:none; \}/, 'Our number name moves to the tooltip so four tabs fit beside the details panel')
  assert.match(tabs, /@media \(max-width:768px\) \{[^}]*\}\s*\.thread-tab \{ min-height:44px; \}\s*\.thread-tab-endpoint, \.thread-tab-person, \.thread-tab-via \{ max-width:120px; \}/)
  assert.match(tabs, /\.thread-tab-icon, \.thread-tab-provider, \.thread-tab-unread \{ flex:none; \}/)
  assert.match(tabs, /new ResizeObserver\(measure\)/)
  assert.match(tabs, /@scroll\.passive="measure"/)
  assert.match(tabs, /scrollIntoView\?\.\(\{ block: 'nearest', inline: 'nearest' \}\)/)
  assert.doesNotMatch(tabs, /setInterval|setTimeout/)
})

test('a list row marks each channel and the one holding the unread message', () => {
  const marks = rowChannels({ threads: [{ channel: 'CH-MAIL', provider: 'Email', endpoint: 'ravi@example.invalid', unread: true },
    { channel: 'CH-SALES', provider: 'WhatsApp', endpoint: '919000000001', unread: false }] })
  assert.deepEqual(marks.map(mark => [mark.icon, mark.unread, mark.label]), [['mail', true, 'Email ravi@example.invalid, unread'],
    ['message-circle', false, 'WhatsApp +91 90000 00001']])
  assert.deepEqual(rowChannels({}), [])
})

test('a read chat the customer wrote last waits for a reply after an hour', () => {
  const now = Date.parse('2026-11-24T12:00:00')
  assert.equal(waitingLabel({ last_direction: 'Incoming', unread: 0, latest_at: '2026-11-22 10:00:00' }, now), 'Waiting 2d')
  assert.equal(waitingLabel({ last_direction: 'Incoming', unread: 0, latest_at: '2026-11-24 09:30:00' }, now), 'Waiting 2h')
  assert.equal(waitingLabel({ last_direction: 'Incoming', unread: 0, latest_at: '2026-11-24 11:30:00' }, now), '')
  assert.equal(waitingLabel({ last_direction: 'Incoming', unread: 2, latest_at: '2026-11-22 10:00:00' }, now), '', 'Unread already shows')
  assert.equal(waitingLabel({ last_direction: 'Outgoing', unread: 0, latest_at: '2026-11-22 10:00:00' }, now), '')
})

const source = (await read('composables/useMessages.js')).replace(/^import .*\n/gm, '').replace('export function', 'const announceOwnSend = () => {}, recordOwnMessages = () => {}\nfunction')
const make = new Function('ref', 'computed', 'watch', 'onMounted', 'onBeforeUnmount', 'useRealtimeRefresh', 'coreApi',
  'resetRecipient', 'sha256Hex', 'randomUUID', 'messageData', 'objectValue', 'coordinates', 'inject', 'composerKinds', 'defaultSendSource',
  source + '\nreturn useMessages({ threads: true });')
const deferred = () => { let resolve, reject; const promise = new Promise((done, fail) => { resolve = done; reject = fail }); return { promise, resolve, reject } }
const message = (name, channel, endpoint, direction = 'Incoming') => ({ name, channel, sender_endpoint: endpoint, relay_contact: 'RELAY-CON-1',
  direction, content: name, creation: '2026-11-24 10:00:' + name.slice(-2), provider_context: { provider: channel === 'CH-MAIL' ? 'Email' : 'WhatsApp' } })
const sales = [message('RELAY-MSG-0000000001', 'CH-SALES', '919000000001'), message('RELAY-MSG-0000000004', 'CH-SALES', '919000000001', 'Outgoing')]

function fixture(t, override = () => {}) {
  const memory = {}, previous = {}
  for (const key of ['document', 'window', 'sessionStorage', 'location']) previous[key] = globalThis[key]
  globalThis.document = { visibilityState: 'visible' }
  globalThis.window = { history: { pushState() {}, replaceState() {} } }
  globalThis.location = { hash: '' }
  globalThis.sessionStorage = Object.assign(memory, { getItem: key => memory[key], setItem: (key, value) => memory[key] = value, removeItem: key => delete memory[key] })
  const calls = [], scope = effectScope()
  let uuid = 0
  const api = async (method, values) => {
    calls.push({ method, values })
    const response = override(method, values)
    if (response !== undefined) return response
    if (method === 'api.conversation_channels') return { items: [{ value: 'CH-SALES' }, { value: 'CH-SUPPORT' }] }
    if (method === 'messaging.pending_messages' || method === 'messaging.action_snapshots') return { items: [] }
    if (method === 'api.messages' || method === 'business_inbox.messages') {
      const items = sales.filter(row => row.channel === values.channel && row.sender_endpoint === values.sender_endpoint)
      return { items, first: items[0]?.name, last: items.at(-1)?.name, ingestion_cursor: items.at(-1)?.name, has_more: false }
    }
    if (method === 'messaging.send') return { status: 'Submitted', action: 'RELAY-MA-0000000001' }
    if (method === 'business_inbox.context') return { name: 'C1', title: 'Ravi Textiles' }
    throw Error('Unexpected method: ' + method)
  }
  const state = scope.run(() => make(ref, computed, watch, () => {}, () => {}, () => {}, api, resetRecipient, sha256Hex,
    () => 'key-' + ++uuid, messageData, objectValue, coordinates, injectCapabilities, composerKinds, defaultSendSource))
  t.after(() => { scope.stop(); for (const [key, value] of Object.entries(previous)) globalThis[key] = value })
  return { state, calls, sends: () => calls.filter(call => call.method === 'messaging.send').map(call => call.values) }
}

test('opening a chat or a record reads no mixed timeline; a thread reads only its channel and endpoint', async t => {
  const { state, calls } = fixture(t)
  await state.open('RELAY-CON-1')
  await state.openBusiness('Customer', 'C1', false)
  assert.equal(calls.some(call => ['api.messages', 'business_inbox.messages'].includes(call.method)), false)
  await state.openThread(thread('sales', { first_unread: 'RELAY-MSG-0000000001' }))
  assert.deepEqual(calls.filter(call => call.method === 'business_inbox.messages').map(call => call.values),
    [{ doctype: 'Customer', name: 'C1', limit: 50, channel: 'CH-SALES', sender_endpoint: '919000000001' }])
  assert.equal(state.source.value.name, 'RELAY-MSG-0000000004', 'The newest message of the thread is the reply source')
  assert.equal(state.firstUnread.value, 'RELAY-MSG-0000000001', 'The thread opens at its first unread message')
})

test('a reply on an open thread is locked to its channel and endpoint', async t => {
  const { state, sends } = fixture(t)
  await state.open('RELAY-CON-1')
  await state.openThread(thread('sales'))
  state.body.value = 'Sharing the invoice now'
  await state.send()
  const [request] = sends()
  assert.equal(request.message, 'RELAY-MSG-0000000004')
  assert.equal('via' in request, false, 'No server-side channel choice')
  assert.equal('channels' in request, false, 'No extra channels')
})

test('a send shows at once as a greyed pending bubble on its thread, then turns normal or offers retry', async t => {
  const response = deferred()
  let fail = true
  const { state, sends } = fixture(t, method => method === 'messaging.send' ? (fail ? response.promise : undefined) : undefined)
  await state.open('RELAY-CON-1')
  await state.openThread(thread('sales'))
  state.body.value = 'On its way'
  const sending = state.send()
  const pending = state.displayRows.value.find(row => row._pending)
  assert.deepEqual([pending._pending, pending.status, pending.content, pending.channel, pending.sender_endpoint],
    [true, 'Sending', 'On its way', 'CH-SALES', '919000000001'], 'Shown before the server answers')
  response.reject(Error('Connection lost'))
  await sending
  const failed = state.displayRows.value.find(row => row._pending)
  assert.equal(failed.status, 'Unconfirmed')
  fail = false
  await state.retryPending(failed)
  assert.equal(sends().length, 2)
  assert.equal(sends()[0].request_key, sends()[1].request_key, 'Retry reuses the request key, so it cannot send twice')
  assert.equal(state.displayRows.value.some(row => row._pending), false, 'The acknowledged send is a normal message')
})

test('a pending send of another thread stays on its own tab', async t => {
  const { state } = fixture(t, method => method === 'messaging.pending_messages' ? { items: [
    { name: 'pending:RELAY-MA-1', action: 'RELAY-MA-1', scope: 'RELAY-CON-1', channel: 'CH-SALES', sender_endpoint: '919000000002', _pending: true, status: 'Failed', creation: '2026-11-24 10:05:00' },
    { name: 'pending:RELAY-MA-2', action: 'RELAY-MA-2', scope: 'RELAY-CON-1', channel: 'CH-SALES', sender_endpoint: '919000000001', _pending: true, status: 'Failed', creation: '2026-11-24 10:06:00' }] } : undefined)
  await state.open('RELAY-CON-1')
  await state.openThread(thread('sales'))
  assert.deepEqual(state.displayRows.value.filter(row => row._pending).map(row => row.action), ['RELAY-MA-2'])
})

test('threads update from socket events only; nothing polls', async () => {
  const files = await Promise.all(['composables/useConversationThreads.js', 'components/messages/ThreadTabs.vue', 'components/messages/ThreadDetails.vue',
    'components/messages/ReplyLock.vue', 'components/messages/InboxDirectory.vue', 'components/ConnectedMessages.vue'].map(read))
  for (const file of files) assert.doesNotMatch(file, /setInterval|polling/i)
  assert.match(files[0], /useRealtimeRefresh\(\[\], \['messages', 'reads', 'chats', 'contacts'\]/)
})

test('a re-layout that reports the same position saves nothing', async t => {
  const { state, calls } = fixture(t, method => method === 'inbox.save_view' ? { saved: true } : undefined)
  await state.open('RELAY-CON-1')
  const position = { name: 'RELAY-MSG-0000000004', offset: 12, atBottom: true }
  for (const value of [position, { ...position }, { ...position, offset: 40, atBottom: false }]) {
    state.rememberPosition(value)
    await new Promise(resolve => setTimeout(resolve, 850))
  }
  assert.deepEqual(calls.filter(call => call.method === 'inbox.save_view').map(call => call.values.offset), [12, 40])
})

test('the set of known rows of a thread is bounded and starts over in another chat', async () => {
  const thread = await read('components/messages/MessageThread.vue')
  assert.match(thread, /if \(known\.size > 2 \* list\.length \+ 200\) known = new Set\(list\.map\(row => row\.name\)\);/)
  assert.match(thread, /watch\(\(\) => props\.selected, \(\) => \{ known = null; fresh\.value = new Set\(\); clearTimeout\(freshTimer\); \}\);/)
})
