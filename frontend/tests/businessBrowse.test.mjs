import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, nextTick, ref, watch, reactive } from 'vue'
import { chatListRefresh, realtimeRefreshQueue, scheduleEvent } from '../src/services/realtimeRefreshQueue.js'
import { announceOwnSend, lastOwnSend, ownSendOf, recordOwnMessages } from '../src/services/ownSends.js'
import { appendTiles, chatTile, mergeTiles, moveSentTile, sentTile, rootBrowse, readBrowse, browseRoute, enterBrowse, browseCrumbs, levelLabel, searchLabel, tileCount, tileKey, tileUnread } from '../src/services/businessBrowse.js'
import { useDebouncedSearch } from '../src/composables/useDebouncedSearch.js'
import { useLoadMore } from '../src/composables/useLoadMore.js'
import { browser } from './browserHistory.js'

const settle = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
async function component(t, props = {}, api) {
  const source = await readFile(new URL('../src/components/messages/BusinessDirectory.vue', import.meta.url), 'utf8')
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*\n/gm, '')
  const mounted = [], scope = effectScope(), emitted = []
  let realtime, liveKinds
  const globals = { computed, ref, watch, nextTick, useDebouncedSearch, useLoadMore, appendTiles, chatTile, mergeTiles, moveSentTile, sentTile, chatListRefresh, lastOwnSend, ownSendOf, tileKey, browseCrumbs, browseRoute, enterBrowse, levelLabel, readBrowse, searchLabel, tileCount, tileUnread,
    defineProps: () => props, defineEmits: () => (...args) => emitted.push(args),
    onMounted: callback => mounted.push(callback), onBeforeUnmount() {}, useRealtimeRefresh(_doctypes, kinds, refresh) { realtime = refresh; liveKinds = kinds }, coreApi: api }
  const state = scope.run(() => new Function(...Object.keys(globals), script + '\nreturn { state, query, items, fields, people, crumbs, next, loading, error, choose, navigate, load, search, moreSentinel };')(...Object.values(globals)))
  t.after(() => scope.stop())
  for (const callback of mounted) callback()
  await settle()
  return { ...state, emitted, realtime: kinds => realtime({ kinds: new Set(kinds) }), live: batch => realtime(batch),
    // Live events as the socket delivers them, through the same kind filter and queue as useRealtimeRefresh.
    events: async list => { const queue = realtimeRefreshQueue(realtime, () => true, 0); for (const event of list) scheduleEvent(queue, liveKinds, event); await new Promise(resolve => setTimeout(resolve, 5)); await settle(); queue.dispose() } }
}

const type = { kind: 'type', doctype: 'Local Supplier', label: 'Suppliers', unread: 12 }
const blank = { kind: 'group', field: 'region', value: '', label: 'Not set', unread: 12 }
const team = { kind: 'group', field: 'team', value: 'North / A&B', label: 'North / A&B', unread: 12 }
const record = { kind: 'record', name: 'local-1', label: 'Local record', unread: 12 }

function api(calls, contacts = false) {
  return async (method, values) => {
    calls.push([method, values])
    if (method === 'api.contact_directory') return { items: [{ name: 'person-1', full_name: 'Local person', mobile_no: '555001' }], next: null }
    if (method === 'inbox.directory') return { items: [], next: null }
    const path = JSON.parse(values.path)
    const items = !values.doctype ? (contacts ? [type, { kind: 'unlinked', contact_count: 1 }] : [type]) : path.length === 0 ? [blank] : path.length === 1 ? [team] : [record]
    return { items, next: null, fields: values.doctype ? [{ fieldname: 'region', label: 'Region' }, { fieldname: 'team', label: 'Team' }] : [] }
  }
}

test('group URLs preserve blank values and special characters; breadcrumbs truncate the path', () => {
  let state = enterBrowse(rootBrowse(), type)
  state = enterBrowse(state, blank)
  state = enterBrowse(state, team)
  assert.deepEqual(readBrowse(browseRoute('#/messages', state)), state)
  const crumbs = browseCrumbs(state)
  assert.deepEqual(crumbs.map(row => row.label), ['Business types', 'Local Supplier', 'Not set', 'North / A&B'])
  assert.deepEqual(crumbs[2].state.path, [''])
  assert.deepEqual(readBrowse('#/messages?group_path=%7B%7D').path, [])
})

test('Inbox opens type, each group level and the existing business thread; Back restores each level', async t => {
  const history = browser(t, '#/messages'), calls = []
  const view = await component(t, {}, api(calls))
  assert.equal(view.items.value[0].kind, 'type')
  view.choose(type); await settle()
  view.choose(blank); await settle()
  view.choose(team); await settle()
  assert.equal(view.items.value[0].kind, 'record')
  view.choose(record)
  assert.deepEqual(view.emitted.at(-1), ['select', type.doctype, record])
  history.history.back(); await settle()
  assert.deepEqual(view.state.value.path, [''])
  history.history.back(); await settle()
  assert.deepEqual(view.state.value.path, [])
  history.history.back(); await settle()
  assert.equal(view.state.value.doctype, '')
  assert.equal(view.items.value[0].kind, 'type')
})

test('Contacts has no flat root, unlinked is one root tile, and record contacts use the exact business pair', async t => {
  browser(t, '#/contacts'); const calls = []
  const view = await component(t, { contacts: true }, api(calls, true))
  assert.deepEqual(view.items.value.map(row => row.kind), ['type', 'unlinked'])
  view.choose(type); await settle()
  view.choose(blank); await settle()
  view.choose(team); await settle()
  view.choose(record); await settle()
  assert.deepEqual(calls.at(-1), ['api.contact_directory', { query: '', after: null, business_type: type.doctype, business_name: record.name, unlinked: 0 }])
  view.choose(view.items.value[0])
  assert.deepEqual(view.emitted.at(-1), ['contact', 'person-1'])
  view.query.value = '555'; await nextTick(); await view.search()
  assert.deepEqual(calls.at(-1), ['api.contact_directory', { query: '555', after: null, business_type: type.doctype, business_name: record.name, unlinked: 0 }],
    'Contact search stays inside the record')
  view.navigate(rootBrowse()); await settle()
  view.choose({ kind: 'unlinked' }); await settle()
  assert.equal(calls.at(-1)[1].unlinked, 1)
})

test('Chats All lists the chats no business record covers below the type tiles and pages them', async t => {
  browser(t, '#/messages'); const calls = []
  const chat = after => ({ name: after ? 'RELAY-CON-2' : 'RELAY-CON-1', title: after ? 'Second chat' : '9876543210', latest_preview: 'Hello', unread: 2 })
  const props = reactive({ filters: { channels: '["ch1"]' } })
  const view = await component(t, props, async (method, values) => {
    calls.push([method, values])
    if (method === 'inbox.directory') return { items: [chat(values.after)], next: values.after ? null : { after: 'cursor-1' } }
    return { items: [type], next: null, fields: [] }
  })
  assert.deepEqual(view.items.value.map(row => [row.kind, row.label]), [['type', 'Suppliers'], ['chat', '9876543210']])
  assert.deepEqual(calls.at(-1), ['inbox.directory', { rows: 'business', mode: 'unlinked', query: '', channels: '["ch1"]' }])
  assert.equal(tileUnread(view.items.value[1]), 2)
  await view.load(true)
  assert.deepEqual(calls.at(-1)[1].after, 'cursor-1')
  assert.deepEqual(view.items.value.map(row => row.name), [undefined, 'RELAY-CON-1', 'RELAY-CON-2'])
  assert.equal(view.next.value, null)
  view.choose(view.items.value[1])
  assert.deepEqual(view.emitted.at(-1), ['chat', 'RELAY-CON-1'])
  props.filters = { business_type: 'Local Supplier' }; await settle()
  assert.equal(calls.at(-1)[0], 'business_groups.browse', 'A business type filter has no unlinked chats')
  view.choose(type); await settle()
  assert.equal(calls.filter(([method]) => method === 'inbox.directory').length, 2)
})

test('a no-group type goes straight to records; paging and failed requests can retry', async t => {
  browser(t, '#/messages'); const calls = []; let fail = true
  const view = await component(t, {}, async (method, values) => {
    calls.push(values)
    if (!values.doctype) return { items: [type], next: null }
    if (fail) throw Error('Temporary failure')
    return { items: [{ ...record, name: values.start ? 'local-2' : 'local-1' }], next: values.start ? null : 30 }
  })
  view.choose(type); await settle()
  assert.equal(view.error.value, 'Temporary failure')
  fail = false; await view.load()
  assert.equal(view.items.value[0].kind, 'record')
  const observers = [], originalObserver = globalThis.IntersectionObserver
  globalThis.IntersectionObserver = class { constructor(callback) { this.callback = callback; observers.push(this) } observe() {} disconnect() {} }
  t.after(() => { globalThis.IntersectionObserver = originalObserver })
  view.moreSentinel.value = {}; await settle()
  await observers.at(-1).callback([{ isIntersecting: true }]); await settle()
  assert.deepEqual(view.items.value.map(row => row.name), ['local-1', 'local-2'])
  assert.equal(view.next.value, null)
  assert.deepEqual(JSON.parse(calls.at(-1).path), [])
})

test('reading the open record refreshes only its tile; other changes reload the level', async t => {
  browser(t, '#/messages'); const calls = []; let unread = 12
  const view = await component(t, { selected: record.name, selectedDoctype: type.doctype }, async (method, values) => {
    calls.push(values)
    if (!values.doctype) return { items: [type], next: null }
    const rows = [{ ...record, doctype: type.doctype, unread }, { ...record, doctype: type.doctype, name: 'local-2' }]
    return { items: rows.filter(row => !values.business_name || row.name === values.business_name), next: null }
  })
  view.choose(type); await settle()
  const tiles = view.items.value, other = tiles[1]
  unread = 0; calls.length = 0
  await view.realtime(['reads'])
  assert.equal(view.items.value, tiles, 'The list is not replaced or cleared')
  assert.equal(view.items.value[0].unread, 0)
  assert.equal(view.items.value[1], other)
  assert.deepEqual(calls.map(values => [values.business_type, values.business_name]), [[type.doctype, record.name]])
  await view.realtime(['reads', 'chats'])
  assert.equal(view.items.value, tiles, 'The shared unread count of the open record changed too')
  assert.equal(calls.length, 2)
  await view.realtime(['reads', 'messages']); await settle()
  assert.equal(view.items.value[0], tiles[0], 'A new message updates the tiles in place')
  await view.realtime(['permissions']); await settle()
  assert.notEqual(view.items.value[0], tiles[0])
})

test('a send or receipt never reloads the list: receipts read nothing, a new message moves tiles in place', async t => {
  browser(t, '#/messages'); const calls = []; let first = ['local-1', 'local-2']
  const view = await component(t, { selected: 'local-2', selectedDoctype: type.doctype }, async (method, values) => {
    calls.push(values)
    if (!values.doctype) return { items: [type], next: null }
    const names = values.start ? ['local-3'] : first
    return { items: names.map(name => ({ ...record, doctype: type.doctype, name, last_activity: name })), next: values.start ? null : 30 }
  })
  view.choose(type); await settle()
  await view.load(true)
  const shown = [...view.items.value]
  calls.length = 0
  await view.realtime(['receipts']); await settle()
  assert.equal(calls.length, 0, 'A delivery receipt reads nothing')
  first = ['local-2', 'local-1']
  let cleared = false
  const stop = watch(() => view.items.value.length, length => { if (!length) cleared = true }, { flush: 'sync' })
  await view.realtime(['messages', 'receipts']); await settle()
  stop()
  assert.equal(cleared, false, 'The list is never emptied while it refreshes')
  assert.equal(view.loading.value, false)
  assert.equal(calls.length, 1, 'One read of the first page')
  assert.deepEqual(view.items.value.map(tile => tile.name), ['local-2', 'local-1', 'local-3'])
  assert.equal(view.items.value[0], shown[1], 'The moved tile is the same object')
  assert.equal(view.items.value[2], shown[2], 'A tile of a later page stays loaded')
})

// A send's events as the queue batches them: the shared room's event has only the change key, the open record's room
// event names the message too. Three sends make three such pairs.
const sendBatch = (names, extra = {}) => ({ kinds: new Set(['messages', 'receipts']), messages: new Set(names),
  changes: new Set(names.map(name => 'change-' + name)), open: new Set(names.map(name => 'change-' + name)), unknown: false, ...extra })

test('own sends move their tile at once and their live events read nothing; a change elsewhere reads the page once', async t => {
  browser(t, '#/messages'); const calls = []
  const view = await component(t, { selected: 'local-2', selectedDoctype: type.doctype }, async (method, values) => {
    calls.push([method, values])
    if (!values.doctype) return { items: [type], next: null }
    return { items: ['local-1', 'local-2'].map(name => ({ ...record, doctype: type.doctype, name, last_activity: '2026-11-05 09:00:00' })), next: null }
  })
  view.choose(type); await settle()
  const shown = [...view.items.value]
  calls.length = 0
  const conversation = { contact: '', business_doctype: type.doctype, business_name: 'local-2', preview: 'Order ready' }
  for (const index of [1, 2, 3]) {
    announceOwnSend(conversation); await settle()
    recordOwnMessages(conversation, ['RELAY-MSG-OWN-' + index])
    await view.live(sendBatch(['RELAY-MSG-OWN-' + index])); await settle()
  }
  assert.deepEqual(view.items.value.map(tile => tile.name), ['local-2', 'local-1'], 'The sent tile moved to the top')
  assert.equal(view.items.value[0], shown[1], 'The moved tile is the same object')
  assert.notEqual(view.items.value[0].last_activity, '2026-11-05 09:00:00')
  assert.deepEqual(calls, [], 'Three sends and their status updates read nothing')
  await view.live(sendBatch(['RELAY-MSG-OWN-1'], { kinds: new Set(['receipts']) })); await settle()
  assert.deepEqual(calls, [], 'A receipt reads nothing')
  await view.live(sendBatch(['RELAY-MSG-IN-1'])); await settle()
  assert.deepEqual(calls.map(([, values]) => values.business_name), ['local-2'], 'A customer reply in the open record reads only its tile')
  calls.length = 0
  await view.live({ ...sendBatch([]), changes: new Set(['change-elsewhere']), open: new Set() }); await settle()
  assert.deepEqual(calls.map(([method]) => method), ['business_groups.browse'], 'A change in another conversation reads the first page once')
  assert.ok(shown.every(tile => view.items.value.includes(tile)), 'and keeps the shown tile objects')
  calls.length = 0
  recordOwnMessages({ ...conversation, business_name: 'local-9' }, ['RELAY-MSG-OWN-9'])
  await view.live(sendBatch(['RELAY-MSG-OWN-9'])); await settle()
  assert.equal(calls.length, 1, 'A send to a record that is not shown reads the first page')
})

// The socket events of one send to an open record chat, in the order a real send brings them: the Hub event
// changes of the send and of its status callbacks, the message in both rooms, and its receipt in both rooms.
const sendEvents = name => [{ kind: 'message_actions' }, { kind: 'incoming' },
  { change: 'c-' + name, kind: 'messages', messages: [name] }, { change: 'c-' + name, kind: 'messages' }, { kind: 'incoming' },
  { change: 'r-' + name, kind: 'messages', messages: [name], receipt: 1 }, { change: 'r-' + name, kind: 'messages', receipt: 1 }, { kind: 'incoming' }]

test('the socket events of three own sends, status callbacks included, read nothing', async t => {
  browser(t, '#/messages'); const calls = []
  const view = await component(t, { selected: 'local-2', selectedDoctype: type.doctype }, async (method, values) => {
    calls.push([method, values])
    if (!values.doctype) return { items: [type], next: null }
    return { items: ['local-1', 'local-2'].map(name => ({ ...record, doctype: type.doctype, name, last_activity: '2026-11-05 09:00:00' })), next: null }
  })
  view.choose(type); await settle()
  calls.length = 0
  const conversation = { contact: '', business_doctype: type.doctype, business_name: 'local-2', preview: 'Order ready' }
  for (const index of [1, 2, 3]) {
    announceOwnSend(conversation); await settle()
    recordOwnMessages(conversation, ['RELAY-MSG-SEND-' + index])
    await view.events(sendEvents('RELAY-MSG-SEND-' + index))
  }
  assert.deepEqual(view.items.value.map(tile => tile.name), ['local-2', 'local-1'])
  assert.deepEqual(calls, [], 'No page or row read for own sends')
  await view.events([{ change: 'c-elsewhere', kind: 'messages' }])
  assert.deepEqual(calls.map(([method]) => method), ['business_groups.browse'], 'A change elsewhere still reads the first page')
})

test('a batch is in the open conversation only when every change also came with its message names', () => {
  const own = name => name.startsWith('own')
  assert.equal(chatListRefresh(sendBatch(['own-1', 'own-2']), own), 'own')
  assert.equal(chatListRefresh(sendBatch(['own-1', 'in-1']), own), 'selected')
  assert.equal(chatListRefresh(sendBatch(['own-1'], { kinds: new Set(['messages', 'reads']) }), own), 'selected')
  assert.equal(chatListRefresh(sendBatch(['own-1'], { unknown: true }), own), 'loaded', 'A change without a key may be anywhere')
  assert.equal(chatListRefresh({ ...sendBatch(['own-1']), changes: new Set(['change-own-1', 'other']) }, own), 'loaded')
  assert.equal(chatListRefresh({ kinds: new Set(['messages']) }, own), 'loaded', 'An older server sends no change keys')
  assert.equal(chatListRefresh({ kinds: new Set(['receipts']) }, own), 'none')
  assert.equal(chatListRefresh({ kinds: new Set(['permissions']) }, own), 'reload')
})

test('a record that moved to the next page between requests is shown once', async t => {
  browser(t, '#/messages')
  const view = await component(t, {}, async (method, values) => {
    if (!values.doctype) return { items: [type], next: null }
    const names = values.start ? ['local-2', 'local-3'] : ['local-1', 'local-2']
    return { items: names.map(name => ({ ...record, name })), next: values.start ? null : 30 }
  })
  view.choose(type); await settle()
  await view.load(true)
  assert.deepEqual(view.items.value.map(row => row.name), ['local-1', 'local-2', 'local-3'])
  assert.deepEqual(appendTiles([type], [type, { ...type, doctype: 'Other' }]).map(row => row.doctype), ['Local Supplier', 'Other'])
})

test('an older request cannot replace results after navigating to another type', async t => {
  browser(t, '#/messages'); let finish
  const view = await component(t, {}, async (method, values) => {
    if (values.doctype === 'Slow') return new Promise(resolve => { finish = resolve })
    return { items: [type], next: null }
  })
  view.choose({ ...type, doctype: 'Slow' }); await settle()
  view.navigate(rootBrowse()); await settle()
  finish({ items: [record], next: null }); await settle()
  assert.equal(view.items.value[0].kind, 'type')
})

test('Back restores Contacts and Inbox searches after opening details and after remounting', async t => {
  for (const contacts of [true, false]) {
    const base = contacts ? '#/contacts' : '#/messages'
    const history = browser(t, base), calls = []
    const view = await component(t, { contacts }, api(calls, contacts))
    view.choose(contacts ? { kind: 'unlinked' } : type); await settle()
    view.query.value = 'Alice & 555'; await settle(); await view.search()
    const parent = location.hash
    assert.equal(readBrowse(parent).query, 'Alice & 555')
    view.choose(contacts ? { kind: 'contact', name: 'alice' } : record)
    history.history.pushState({ relayDetail: true }, '', parent + '&' + (contacts ? 'contact=alice' : 'business_name=local-1'))
    history.history.back(); await settle(); await view.search()
    assert.equal(view.query.value, 'Alice & 555')
    assert.equal(calls.at(-1)[1].query, 'Alice & 555')
    assert.equal(calls.at(-1)[0], contacts ? 'api.contact_directory' : 'business_groups.browse')
    const restored = await component(t, { contacts }, api(calls, contacts))
    assert.equal(restored.query.value, 'Alice & 555')
  }
})

test('drilling into a searched group keeps its search in the previous history entry', async t => {
  const history = browser(t, '#/messages'), calls = []
  const view = await component(t, {}, api(calls))
  view.query.value = 'Alpha'; await settle(); await view.search()
  view.choose(type); await settle()
  assert.equal(view.query.value, '')
  history.history.back(); await settle()
  assert.equal(view.query.value, 'Alpha')
})

test('channel, type and record filters reach browsing and changing filters reloads from root', async t => {
  browser(t, '#/messages'); const calls = []
  const props = reactive({ filters: { channels: '["ch1"]', medium: 'WhatsApp', business_type: 'Local Supplier', business_name: 'local-1' } })
  const view = await component(t, props, api(calls))
  assert.equal(calls.at(-1)[1].channels, '["ch1"]')
  assert.equal(calls.at(-1)[1].business_name, 'local-1')
  view.choose(type); await settle()
  props.filters = { business_type: 'Other' }; await settle()
  assert.equal(calls.at(-1)[1].business_type, 'Other')
  assert.equal(calls.at(-1)[1].doctype, null)
})

test('tiles use singular nouns and unread record totals at group levels', () => {
  assert.equal(tileCount(1, 'record'), '1 record')
  assert.equal(tileCount(2, 'record'), '2 records')
  assert.equal(tileCount(1, 'contact'), '1 contact')
  assert.equal(tileCount(0, 'contact'), '0 contacts')
  assert.equal(tileCount(1, 'unread message'), '1 unread message')
  assert.equal(tileCount(1, 'unread record'), '1 unread record')
  for (const kind of ['type', 'group']) assert.equal(tileUnread({ kind, unread: 4278, unread_records: 121 }), 121)
  assert.equal(tileUnread({ kind: 'record', unread: 42, unread_records: 1 }), 42)
})

test('rendered root has one Business types label and Contacts tiles have contact counts without unread badges', async t => {
  const { compile } = await import('@vue/compiler-dom')
  const Vue = await import('vue')
  const { renderToString } = await import('@vue/server-renderer')
  const source = await readFile(new URL('../src/components/messages/BusinessDirectory.vue', import.meta.url), 'utf8')
  const template = source.slice(source.indexOf('<template>') + 10, source.indexOf('<style scoped>')).replace(/<\/template>\s*$/, '')
  const render = new Function('Vue', compile(template, { mode: 'function', prefixIdentifiers: true }).code)(Vue)
  for (const contacts of [false, true]) {
    browser(t, contacts ? '#/contacts' : '#/messages')
    const view = await component(t, { contacts }, async method => method === 'inbox.directory' ? { items: [], next: null } : ({ items: [
      { kind: 'type', label: 'Local', record_count: 1, contact_count: 2, unread: 4278, unread_records: 121 },
    ], fields: [], next: null }))
    const app = Vue.createSSRApp({ render, setup: () => ({ ...view, contacts, busy: false,
      selected: '', selectedDoctype: '', heading: null, levelLabel, searchLabel, tileCount, tileKey, tileUnread, listTime: () => '' }) })
    for (const name of ['Avatar', 'Button', 'ErrorMessage', 'FeatherIcon', 'TextInput', 'LoadingRows']) {
      app.component(name, { setup: () => () => Vue.h('span') })
    }
    const html = await renderToString(app)
    assert.equal((html.match(/Business types/g) || []).length, 1)
    if (contacts) {
      assert.match(html, /2 contacts/)
      assert.doesNotMatch(html, /directory-unread|unread messages|unread records/)
    } else {
      assert.match(html, /1 record/)
      assert.doesNotMatch(html, /1 records|4278/)
      assert.match(html, /121 unread records/)
    }
  }
})

test('search filters the shown level and the placeholder names it', async t => {
  for (const contacts of [false, true]) {
    browser(t, contacts ? '#/contacts' : '#/messages'); const calls = []
    const view = await component(t, { contacts }, api(calls, contacts))
    const placeholder = () => searchLabel(view.state.value, view.fields.value)
    assert.equal(placeholder(), 'Search business types')
    view.query.value = 'Supp'; await settle(); await view.search()
    const root = calls.findLast(([method]) => method === 'business_groups.browse')
    assert.deepEqual([root[1].query, root[1].doctype], ['Supp', null])
    if (!contacts) assert.deepEqual([calls.at(-1)[0], calls.at(-1)[1].query], ['inbox.directory', 'Supp'], 'Chats All also searches its chats')
    view.choose(type); await settle()
    assert.equal(placeholder(), 'Search Region')
    view.query.value = 'North'; await settle(); await view.search()
    assert.deepEqual([calls.at(-1)[0], calls.at(-1)[1].query, calls.at(-1)[1].path], ['business_groups.browse', 'North', '[]'])
    view.choose(blank); await settle(); view.choose(team); await settle()
    assert.equal(placeholder(), 'Search Local Supplier')
    view.query.value = 'Local'; await settle(); await view.search()
    assert.deepEqual([calls.at(-1)[0], calls.at(-1)[1].path_fields], ['business_groups.browse', '["region","team"]'])
    if (contacts) {
      view.choose(record); await settle()
      assert.equal(placeholder(), 'Search name, number or email')
    }
  }
})

test('a group level is entered once even when a stale tile is clicked again', async t => {
  const history = browser(t, '#/contacts'), calls = []
  const view = await component(t, { contacts: true }, api(calls, true))
  view.choose(type); await settle()
  const partner = { ...blank, value: 'Sampleville - KESTREL TRADERS' }
  view.choose(partner); view.choose(partner); await settle()
  assert.deepEqual(view.state.value.path, ['Sampleville - KESTREL TRADERS'])
  assert.deepEqual(readBrowse(location.hash).pathFields, ['region'])
  history.history.back(); await settle()
  assert.deepEqual(view.state.value.path, [])
  assert.deepEqual(view.crumbs.value.map(row => row.label), ['Business types', 'Local Supplier'])
})

test('a URL saved under an older grouping restarts at the level the server answers', async t => {
  browser(t, '#/contacts?group_type=Customer&group_path=' + encodeURIComponent('["Sampleville","Sampleville"]') + '&group_fields=' + encodeURIComponent('["customer_group","default_sales_partner"]'))
  const calls = []
  const view = await component(t, { contacts: true }, async (method, values) => {
    calls.push(values)
    return { items: [{ kind: 'group', field: 'default_sales_partner', value: 'Sampleville', label: 'Sampleville' }], next: null, path: [], path_fields: [],
      fields: [{ fieldname: 'default_sales_partner', label: 'Sales Partner' }] }
  })
  assert.equal(calls[0].path_fields, '["customer_group","default_sales_partner"]')
  assert.deepEqual(view.state.value.path, [])
  assert.equal(readBrowse(location.hash).path.length, 0)
  assert.deepEqual(view.crumbs.value.map(row => row.label), ['Business types', 'Customer'])
  assert.equal(view.items.value[0].value, 'Sampleville')
  assert.equal(levelLabel(view.state.value, view.fields.value), 'Sales Partner')
})

test('record tiles use the coloured initials avatar and group tiles keep the folder icon', async () => {
  const source = await readFile(new URL('../src/components/messages/BusinessDirectory.vue', import.meta.url), 'utf8')
  assert.match(source, /<Avatar v-if="\['contact', 'record', 'chat'\]\.includes\(tile\.kind\)" :label="tile\.label" \/>/)
  assert.doesNotMatch(source, /file-text/)
  assert.match(source, /'folder'/)
})
