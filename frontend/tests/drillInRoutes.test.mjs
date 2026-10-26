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
import { closeRoute, openRoute } from '../src/useViewRoute.js'

const source = (await readFile(new URL('../src/composables/useMessages.js', import.meta.url), 'utf8'))
  .replace(/^import .*\n/gm, '').replace('export function', 'function')
const make = new Function('ref', 'computed', 'watch', 'onMounted', 'onBeforeUnmount', 'useRealtimeRefresh', 'coreApi',
  'resetRecipient', 'sha256Hex', 'randomUUID', 'messageData', 'objectValue', 'coordinates', 'inject', 'composerKinds',
  'defaultSendSource', 'openRoute', 'closeRoute', source + '\nreturn useMessages();')
const listRoute = '#/messages'
const chatRoute = contact => '#/messages?contact=' + contact

// Browser history stand-in: a stack of { hash, state } entries that fires popstate on back().
function browser(t, hash) {
  const previous = {}
  for (const key of ['document', 'window', 'sessionStorage', 'location']) previous[key] = globalThis[key]
  const entries = [{ hash, state: null }], listeners = []
  let index = 0
  const location = { hash }
  const move = (entry, replace) => {
    if (!replace) entries.splice(++index, Infinity, entry)
    else entries[index] = entry
    location.hash = entry.hash
  }
  const history = {
    get state() { return entries[index].state },
    get length() { return entries.length },
    pushState: (state, title, url) => move({ hash: url, state }, false),
    replaceState: (state, title, url) => move({ hash: url, state }, true),
    back() { index -= 1; location.hash = entries[index].hash; for (const listener of listeners) listener() },
  }
  globalThis.location = location
  globalThis.window = { history, addEventListener: (type, listener) => listeners.push(listener), removeEventListener() {} }
  globalThis.document = { visibilityState: 'visible' }
  globalThis.sessionStorage = { getItem() {}, setItem() {}, removeItem() {} }
  t.after(() => { for (const [key, value] of Object.entries(previous)) globalThis[key] = value })
  return { history, location, entries: () => entries.slice(0, index + 1).map(entry => entry.hash) }
}

async function messages(t) {
  const mounted = []
  const api = async (method, values) => {
    if (method === 'api.conversation_channels') {
      if (values.contact === 'RELAY-CON-MISSING') throw Object.assign(Error('Not permitted'), { status: 403 })
      return { items: [{ value: 'whatsapp' }] }
    }
    if (method === 'inbox.view_state') return {}
    if (method === 'messaging.pending_messages') return { items: [] }
    if (method === 'api.messages') return { items: [], has_more: false }
    throw Error('Unexpected method: ' + method)
  }
  const scope = effectScope()
  const state = scope.run(() => make(ref, computed, watch, callback => mounted.push(callback), () => {}, () => {}, api,
    resetRecipient, sha256Hex, () => 'key', messageData, objectValue, coordinates, injectCapabilities, composerKinds,
    defaultSendSource, openRoute, closeRoute))
  t.after(() => scope.stop())
  for (const callback of mounted) await callback()
  return state
}

const settle = () => new Promise(resolve => setTimeout(resolve, 0))

test('opening a chat from the list adds one entry and switching chats replaces it', t => {
  const page = browser(t, listRoute)
  openRoute(chatRoute('A'), false)
  openRoute(chatRoute('B'), true)
  openRoute(chatRoute('C'), true)
  assert.deepEqual(page.entries(), [listRoute, chatRoute('C')])
  assert.equal(page.history.state.relayList, true)
})

test('opening the current route again does not add an entry', t => {
  const page = browser(t, chatRoute('A'))
  openRoute(chatRoute('A'), false)
  assert.equal(page.history.length, 1)
})

test('closing a chat opened from the list goes back to the list entry', t => {
  const page = browser(t, listRoute)
  openRoute(chatRoute('A'), false)
  closeRoute(listRoute)
  assert.deepEqual(page.entries(), [listRoute])
})

test('closing a deep-linked chat replaces it with the list and keeps the history length', t => {
  const page = browser(t, chatRoute('A'))
  closeRoute(listRoute)
  assert.equal(page.location.hash, listRoute)
  assert.equal(page.history.length, 1)
})

test('Back from a chat opened from the list shows the list', async t => {
  const page = browser(t, listRoute)
  const state = await messages(t)
  openRoute(chatRoute('RELAY-CON-1'), false)
  await state.open('RELAY-CON-1')
  page.history.back()
  await settle()
  assert.equal(state.selected.value, '')
  assert.equal(page.location.hash, listRoute)
})

test('the in-app back button returns to the list entry instead of adding one', async t => {
  const page = browser(t, listRoute)
  const state = await messages(t)
  openRoute(chatRoute('RELAY-CON-1'), false)
  await state.open('RELAY-CON-1')
  state.clearSelection()
  await settle()
  assert.equal(state.selected.value, '')
  assert.deepEqual(page.entries(), [listRoute])
})

test('a conversation link opens that chat directly', async t => {
  browser(t, chatRoute('RELAY-CON-1'))
  const state = await messages(t)
  assert.equal(state.selected.value, 'RELAY-CON-1')
})

test('a missing or forbidden conversation link falls back to the list', async t => {
  const page = browser(t, chatRoute('RELAY-CON-MISSING'))
  const state = await messages(t)
  assert.equal(state.selected.value, '')
  assert.equal(page.location.hash, listRoute)
  assert.equal(page.history.length, 1)
})
