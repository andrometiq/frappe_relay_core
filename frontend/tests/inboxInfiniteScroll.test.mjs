import { useLoadMore } from '../src/composables/useLoadMore.js'
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, nextTick, ref, watch } from 'vue'
import { coreApi } from '../src/services/coreApi.js'
import { defaultMedium, mediumOptions } from '../src/services/enabledChannels.js'
import { mergeChangedRows, mergeFirstPage, newestActivity } from '../src/services/inboxRows.js'
import { heldRefresh, listRefresh } from '../src/services/realtimeRefreshQueue.js'
import { TABS, channelOptions, filterChips, filterParams, loadFilters, saveFilters, withoutFilter, withoutFilters } from '../src/services/inboxFilters.js'

test('the unread chat list loads the next page when its end scrolls into view, and stops at the last page', { timeout: 3000 }, async () => {
  const source = await readFile(new URL('../src/components/messages/InboxDirectory.vue', import.meta.url), 'utf8')
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*\n/gm, '')
  const make = new Function('useLoadMore','defineProps', 'defineEmits', 'inject', 'onMounted', 'onBeforeUnmount', 'computed', 'ref', 'watch', 'coreApi', 'useRealtimeRefresh', 'mediumOptions', 'useQueueCounts', 'defaultMedium', 'useMobileLayout', 'mergeChangedRows', 'mergeFirstPage', 'newestActivity', 'listRefresh', 'heldRefresh', 'useChatFolders',
    'hasManyNumbers', 'TABS', 'channelOptions', 'filterChips', 'filterParams', 'loadFilters', 'saveFilters', 'withoutFilter', 'withoutFilters',
    script + '\nreturn { rows, next, loading, more };').bind(null, useLoadMore)
  const originalFetch = globalThis.fetch, originalWindow = globalThis.window, originalObserver = globalThis.IntersectionObserver
  const requests = [], observers = []
  let mount
  globalThis.window = { frappe: { csrf_token: 'local-fixture' } }
  globalThis.IntersectionObserver = class { constructor(callback) { this.callback = callback; this.live = true; observers.push(this) } observe() {} disconnect() { this.live = false } }
  globalThis.fetch = async url => {
    requests.push(url)
    return Response.json({ message: url.includes('after=page-2')
      ? { items: [{ name: 'contact-2' }], next: null }
      : { items: [{ name: 'contact-1' }], next: { after: 'page-2' } } })
  }
  const visible = async () => {
    observers.filter(observer => observer.live).forEach(observer => observer.callback([{ isIntersecting: true }]))
    await nextTick()
    while (state.loading.value) await new Promise(resolve => setImmediate(resolve))
  }
  const scope = effectScope()
  let state
  try {
    state = scope.run(() => make(() => ({}), () => () => {}, () => ({}), fn => mount = fn, () => {}, computed, ref, watch, coreApi,
      () => {}, mediumOptions, () => ({ counts: ref({}) }), defaultMedium, () => ref(false), mergeChangedRows, mergeFirstPage, newestActivity, listRefresh, heldRefresh,
      () => ({ folders: ref([]), changes: ref(0), moved: ref(null), move: async () => {} }),
      () => false, TABS, channelOptions, filterChips, filterParams, (...args) => ({ ...loadFilters(...args), tab: 'unread' }), saveFilters, withoutFilter, withoutFilters))
    await mount()
    while (state.loading.value) await new Promise(resolve => setImmediate(resolve))
    state.more.value = {}
    await nextTick()
    await visible()
    assert.deepEqual(state.rows.value.map(row => row.name), ['contact-1', 'contact-2'])
    assert.equal(state.next.value, null)
    await visible()
    assert.equal(requests.length, 2, 'The last page must not load again')
    scope.stop()
    assert.ok(observers.every(observer => !observer.live))
  } finally {
    scope.stop()
    globalThis.fetch = originalFetch; globalThis.window = originalWindow; globalThis.IntersectionObserver = originalObserver
  }
})

test('a live change while the next page loads keeps the loaded pages and runs after the load', { timeout: 3000 }, async () => {
  const source = await readFile(new URL('../src/components/messages/InboxDirectory.vue', import.meta.url), 'utf8')
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*\n/gm, '')
  const make = new Function('useLoadMore','defineProps', 'defineEmits', 'inject', 'onMounted', 'onBeforeUnmount', 'computed', 'ref', 'watch', 'coreApi', 'useRealtimeRefresh', 'mediumOptions', 'useQueueCounts', 'defaultMedium', 'useMobileLayout', 'mergeChangedRows', 'mergeFirstPage', 'newestActivity', 'listRefresh', 'heldRefresh', 'useChatFolders',
    'hasManyNumbers', 'TABS', 'channelOptions', 'filterChips', 'filterParams', 'loadFilters', 'saveFilters', 'withoutFilter', 'withoutFilters',
    script + '\nreturn { rows, next, loading, more };').bind(null, useLoadMore)
  const originalFetch = globalThis.fetch, originalWindow = globalThis.window, originalObserver = globalThis.IntersectionObserver
  const requests = [], observers = []
  let mount, live, releasePage2
  const page2 = new Promise(resolve => { releasePage2 = resolve })
  globalThis.window = { frappe: { csrf_token: 'local-fixture' } }
  globalThis.IntersectionObserver = class { constructor(callback) { this.callback = callback; this.live = true; observers.push(this) } observe() {} disconnect() { this.live = false } }
  globalThis.fetch = async url => {
    requests.push(url)
    if (url.includes('after=page-2')) { await page2; return Response.json({ message: { items: [{ name: 'acme-old', last_message_at: '2026-11-01 09:00:00' }], next: null } }) }
    if (url.includes('since=')) return Response.json({ message: { items: [{ name: 'acme-new', last_message_at: '2026-11-06 10:05:00' }], next: null } })
    return Response.json({ message: { items: [{ name: 'acme-1', last_message_at: '2026-11-06 10:00:00' }], next: { after: 'page-2' } } })
  }
  const idle = async () => { await nextTick(); while (state.loading.value) await new Promise(resolve => setImmediate(resolve)); await new Promise(resolve => setImmediate(resolve)) }
  const scope = effectScope()
  let state
  try {
    state = scope.run(() => make(() => ({}), () => () => {}, () => ({}), fn => mount = fn, () => {}, computed, ref, watch, coreApi,
      (_doctypes, _kinds, refresh) => { live = refresh }, mediumOptions, () => ({ counts: ref({}) }), defaultMedium, () => ref(false), mergeChangedRows, mergeFirstPage, newestActivity, listRefresh, heldRefresh,
      () => ({ folders: ref([]), changes: ref(0), moved: ref(null), move: async () => {} }),
      () => false, TABS, channelOptions, filterChips, filterParams, (...args) => ({ ...loadFilters(...args), tab: 'unread' }), saveFilters, withoutFilter, withoutFilters))
    await mount(); await idle()
    state.more.value = {}
    await nextTick()
    observers.filter(observer => observer.live).forEach(observer => observer.callback([{ isIntersecting: true }]))
    await nextTick()
    assert.equal(state.loading.value, true, 'Page 2 is loading')
    await live({ kinds: new Set(['messages']) })
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(requests.length, 2, 'The live change waits for the page load')
    releasePage2(); await idle()
    assert.deepEqual(state.rows.value.map(row => row.name), ['acme-new', 'acme-1', 'acme-old'])
    assert.equal(requests.length, 3)
    assert.match(requests[2], /since=/, 'The held change reads only the changed rows')
  } finally {
    scope.stop()
    globalThis.fetch = originalFetch; globalThis.window = originalWindow; globalThis.IntersectionObserver = originalObserver
  }
})
