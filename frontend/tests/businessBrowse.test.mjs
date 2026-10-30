import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, nextTick, ref, watch, reactive } from 'vue'
import { appendTiles, rootBrowse, readBrowse, browseRoute, enterBrowse, browseCrumbs, levelLabel, searchLabel, tileCount, tileKey, tileUnread } from '../src/services/businessBrowse.js'
import { useDebouncedSearch } from '../src/composables/useDebouncedSearch.js'
import { useLoadMore } from '../src/composables/useLoadMore.js'
import { browser } from './browserHistory.js'

const settle = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
async function component(t, props = {}, api) {
  const source = await readFile(new URL('../src/components/messages/BusinessDirectory.vue', import.meta.url), 'utf8')
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*\n/gm, '')
  const mounted = [], scope = effectScope(), emitted = []
  const globals = { computed, ref, watch, nextTick, useDebouncedSearch, useLoadMore, appendTiles, tileKey, browseCrumbs, browseRoute, enterBrowse, levelLabel, readBrowse, searchLabel, tileCount, tileUnread,
    defineProps: () => props, defineEmits: () => (...args) => emitted.push(args),
    onMounted: callback => mounted.push(callback), onBeforeUnmount() {}, useRealtimeRefresh() {}, coreApi: api }
  const state = scope.run(() => new Function(...Object.keys(globals), script + '\nreturn { state, query, items, fields, people, crumbs, next, loading, error, choose, navigate, load, search, moreSentinel };')(...Object.values(globals)))
  t.after(() => scope.stop())
  for (const callback of mounted) callback()
  await settle()
  return { ...state, emitted }
}

const type = { kind: 'type', doctype: 'Local Supplier', label: 'Suppliers', unread: 12 }
const blank = { kind: 'group', field: 'region', value: '', label: 'Not set', unread: 12 }
const team = { kind: 'group', field: 'team', value: 'North / A&B', label: 'North / A&B', unread: 12 }
const record = { kind: 'record', name: 'local-1', label: 'Local record', unread: 12 }

function api(calls, contacts = false) {
  return async (method, values) => {
    calls.push([method, values])
    if (method === 'api.contact_directory') return { items: [{ name: 'person-1', full_name: 'Local person', mobile_no: '555001' }], next: null }
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
    const view = await component(t, { contacts }, async () => ({ items: [
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
    assert.deepEqual([calls.at(-1)[0], calls.at(-1)[1].query, calls.at(-1)[1].doctype], ['business_groups.browse', 'Supp', null])
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
  const partner = { ...blank, value: 'Bihar - ATAL MARKETING' }
  view.choose(partner); view.choose(partner); await settle()
  assert.deepEqual(view.state.value.path, ['Bihar - ATAL MARKETING'])
  assert.deepEqual(readBrowse(location.hash).pathFields, ['region'])
  history.history.back(); await settle()
  assert.deepEqual(view.state.value.path, [])
  assert.deepEqual(view.crumbs.value.map(row => row.label), ['Business types', 'Local Supplier'])
})

test('a URL saved under an older grouping restarts at the level the server answers', async t => {
  browser(t, '#/contacts?group_type=Customer&group_path=' + encodeURIComponent('["Bihar","Bihar"]') + '&group_fields=' + encodeURIComponent('["customer_group","default_sales_partner"]'))
  const calls = []
  const view = await component(t, { contacts: true }, async (method, values) => {
    calls.push(values)
    return { items: [{ kind: 'group', field: 'default_sales_partner', value: 'Bihar', label: 'Bihar' }], next: null, path: [], path_fields: [],
      fields: [{ fieldname: 'default_sales_partner', label: 'Sales Partner' }] }
  })
  assert.equal(calls[0].path_fields, '["customer_group","default_sales_partner"]')
  assert.deepEqual(view.state.value.path, [])
  assert.equal(readBrowse(location.hash).path.length, 0)
  assert.deepEqual(view.crumbs.value.map(row => row.label), ['Business types', 'Customer'])
  assert.equal(view.items.value[0].value, 'Bihar')
  assert.equal(levelLabel(view.state.value, view.fields.value), 'Sales Partner')
})

test('record tiles use the coloured initials avatar and group tiles keep the folder icon', async () => {
  const source = await readFile(new URL('../src/components/messages/BusinessDirectory.vue', import.meta.url), 'utf8')
  assert.match(source, /<Avatar v-if="tile\.kind === 'contact' \|\| tile\.kind === 'record'" :label="tile\.label" \/>/)
  assert.doesNotMatch(source, /file-text/)
  assert.match(source, /'folder'/)
})
