import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, nextTick, ref, watch } from 'vue'
import { coreApi } from '../src/services/coreApi.js'
import { defaultMedium, mediumOptions } from '../src/services/enabledChannels.js'
import { mergeChangedRows, newestActivity, onlyChangedRows } from '../src/services/inboxRows.js'
import { TABS, channelOptions, filterChips, filterParams, loadFilters, saveFilters, withoutFilter, withoutFilters } from '../src/services/inboxFilters.js'

test('the chat list loads the next page when its end scrolls into view, and stops at the last page', { timeout: 3000 }, async () => {
  const source = await readFile(new URL('../src/components/messages/InboxDirectory.vue', import.meta.url), 'utf8')
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*\n/gm, '')
  const make = new Function('defineProps', 'defineEmits', 'inject', 'onMounted', 'onBeforeUnmount', 'computed', 'ref', 'watch', 'coreApi', 'useRealtimeRefresh', 'mediumOptions', 'useQueueCounts', 'defaultMedium', 'useMobileLayout', 'mergeChangedRows', 'newestActivity', 'onlyChangedRows', 'useChatFolders',
    'hasManyNumbers', 'TABS', 'channelOptions', 'filterChips', 'filterParams', 'loadFilters', 'saveFilters', 'withoutFilter', 'withoutFilters',
    script + '\nreturn { rows, next, loading, more };')
  const originalFetch = globalThis.fetch, originalWindow = globalThis.window, originalObserver = globalThis.IntersectionObserver
  const requests = [], observers = []
  let mount, unmount
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
    state = scope.run(() => make(() => ({}), () => () => {}, () => ({}), fn => mount = fn, fn => unmount = fn, computed, ref, watch, coreApi,
      () => {}, mediumOptions, () => ({ counts: ref({}) }), defaultMedium, () => ref(false), mergeChangedRows, newestActivity, onlyChangedRows,
      () => ({ folders: ref([]), changes: ref(0), moved: ref(null), move: async () => {} }),
      () => false, TABS, channelOptions, filterChips, filterParams, loadFilters, saveFilters, withoutFilter, withoutFilters))
    await mount()
    while (state.loading.value) await new Promise(resolve => setImmediate(resolve))
    state.more.value = {}
    await nextTick()
    await visible()
    assert.deepEqual(state.rows.value.map(row => row.name), ['contact-1', 'contact-2'])
    assert.equal(state.next.value, null)
    await visible()
    assert.equal(requests.length, 2, 'The last page must not load again')
    unmount()
    assert.ok(observers.every(observer => !observer.live))
  } finally {
    scope.stop()
    globalThis.fetch = originalFetch; globalThis.window = originalWindow; globalThis.IntersectionObserver = originalObserver
  }
})
