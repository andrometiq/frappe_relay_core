import { useLoadMore } from '../src/composables/useLoadMore.js'
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, nextTick, ref, watch } from 'vue'
import { coreApi } from '../src/services/coreApi.js'
import { defaultMedium, mediumOptions } from '../src/services/enabledChannels.js'
import { mergeChangedRows, newestActivity, onlyChangedRows } from '../src/services/inboxRows.js'
import { TABS, channelOptions, filterChips, filterParams, loadFilters, saveFilters, storageKey, withoutFilter, withoutFilters } from '../src/services/inboxFilters.js'

const source = await readFile(new URL('../src/components/messages/InboxDirectory.vue', import.meta.url), 'utf8')
const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*\n/gm, '')
const make = new Function('useLoadMore','defineProps', 'defineEmits', 'inject', 'onMounted', 'onBeforeUnmount', 'computed', 'ref', 'watch', 'coreApi', 'useRealtimeRefresh', 'mediumOptions', 'useQueueCounts', 'defaultMedium', 'useMobileLayout', 'mergeChangedRows', 'newestActivity', 'onlyChangedRows', 'useChatFolders',
  'hasManyNumbers', 'INBOX_ROWS', 'TABS', 'channelOptions', 'filterChips', 'filterParams', 'loadFilters', 'saveFilters', 'withoutFilter', 'withoutFilters',
  script + '\nreturn { mode, filters, activeFilters };').bind(null, useLoadMore)
const capabilities = { enabled_channels: ['WhatsApp'], inbox_channels: [
  { name: 'WA-1', label: 'Sales line', address: '+91 1', medium: 'WhatsApp' }, { name: 'WA-2', label: 'Support line', address: '+91 2', medium: 'WhatsApp' }] }
const settle = async () => { for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve)) }

test('saved filters and tab drive the list and counts, and every change is saved for the user', { timeout: 3000 }, async t => {
  const store = new Map(), requests = []
  const original = { fetch: globalThis.fetch, window: globalThis.window, frappe: globalThis.frappe, localStorage: globalThis.localStorage }
  globalThis.window = { frappe: { csrf_token: 'local-fixture' } }
  globalThis.frappe = { session: { user: 'ann@example.invalid' } }
  globalThis.localStorage = { getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value) }
  store.set(storageKey('ann@example.invalid'), JSON.stringify({ tab: 'unlinked', channels: ['WA-2', 'TG-9'], businessType: 'Customer', businessName: 'CUST-1', businessLabel: 'Acme' }))
  globalThis.fetch = async url => { requests.push(Object.fromEntries(new URL(url, 'http://local').searchParams)); return Response.json({ message: { items: [], next: null } }) }
  const scope = effectScope()
  t.after(() => { scope.stop(); Object.assign(globalThis, original) })
  let mount, counted
  const state = scope.run(() => {
    return make(() => ({}), () => () => {}, () => ref(capabilities), fn => mount = fn, () => {}, computed, ref, watch, coreApi, () => {}, mediumOptions,
      (medium, params) => { counted = params; return { counts: ref({}) } }, defaultMedium, () => ref(false), mergeChangedRows, newestActivity, onlyChangedRows,
      () => ({ folders: ref([]), changes: ref(0), moved: ref(null), move: async () => {} }),
      () => false, { rows: 'business' }, TABS, channelOptions, filterChips, filterParams, loadFilters, saveFilters, withoutFilter, withoutFilters)
  })
  await mount(); await settle()
  assert.equal(state.mode.value, 'unlinked')
  assert.deepEqual(requests.at(-1), { rows: 'business', mode: 'unlinked', query: '', medium: 'WhatsApp', channels: '["WA-2"]', business_type: 'Customer', business_name: 'CUST-1' })
  assert.deepEqual(counted.value, { channels: '["WA-2"]', business_type: 'Customer', business_name: 'CUST-1', rows: 'business' }, 'Counts use the same filters as the list')
  assert.deepEqual(state.activeFilters.value.map(item => item.label), ['Support line', 'Customer: Acme'])

  state.mode.value = 'unread'
  state.filters.value = withoutFilter(state.filters.value, 'business')
  await nextTick(); await settle()
  assert.deepEqual(requests.at(-1), { rows: 'business', mode: 'unread', query: '', medium: 'WhatsApp', channels: '["WA-2"]' })
  assert.deepEqual(JSON.parse(store.get(storageKey('ann@example.invalid'))), { tab: 'unread', channels: ['WA-2', 'TG-9'], businessType: '', businessName: '', businessLabel: '' })
})
