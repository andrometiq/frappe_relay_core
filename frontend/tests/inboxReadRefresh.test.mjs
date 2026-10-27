import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, nextTick, ref, watch } from 'vue'
import { coreApi } from '../src/services/coreApi.js'
import { onRealtime } from '../src/services/realtime.js'
import { defaultMedium, mediumOptions } from '../src/services/enabledChannels.js'
import { mergeChangedRows, newestActivity, onlyChangedRows } from '../src/services/inboxRows.js'
import { TABS, channelOptions, filterChips, filterParams, loadFilters, saveFilters, withoutFilter, withoutFilters } from '../src/services/inboxFilters.js'

test('read mutations refresh the unread queue without waiting for a socket, but failed reads do not', { timeout: 3000 }, async () => {
  const source = await readFile(new URL('../src/components/messages/InboxDirectory.vue', import.meta.url), 'utf8')
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*\n/gm, '')
  const make = new Function('defineProps', 'defineEmits', 'inject', 'onMounted', 'computed', 'ref', 'watch', 'coreApi', 'useRealtimeRefresh', 'mediumOptions', 'useQueueCounts', 'defaultMedium', 'useMobileLayout', 'mergeChangedRows', 'newestActivity', 'onlyChangedRows', 'useChatFolders',
    'hasManyNumbers', 'TABS', 'channelOptions', 'filterChips', 'filterParams', 'loadFilters', 'saveFilters', 'withoutFilter', 'withoutFilters',
    script + '\nreturn { mode, rows, loading };')
  const originalFetch = globalThis.fetch, originalWindow = globalThis.window
  let unread = 2, fail = false, loads = 0, mount, off, refreshed
  globalThis.window = { frappe: { csrf_token: 'local-fixture' } }
  globalThis.fetch = async (url, options) => {
    if (options.method === 'GET') {
      assert.match(url, /relay_core.inbox.directory/)
      loads++
      return Response.json({ message: { items: unread ? [{ name: 'contact', unread }] : [] } })
    }
    if (fail) return Response.json({ message: 'Read position belongs to another contact' }, { status: 417 })
    unread = 0
    return Response.json({ message: { unread } })
  }
  const scope = effectScope()
  try {
    const state = scope.run(() => make(() => ({}), () => () => {}, () => ({}), fn => mount = fn, computed, ref, watch, coreApi,
      (_doctypes, kinds, refresh) => { off = onRealtime(event => { if (kinds.includes(event.kind)) refreshed = refresh() }) }, mediumOptions,
      () => ({ counts: ref({}) }), defaultMedium, () => ref(false), mergeChangedRows, newestActivity, onlyChangedRows,
      () => ({ folders: ref([]), changes: ref(0), moved: ref(null), move: async () => {} }),
      () => false, TABS, channelOptions, filterChips, filterParams, loadFilters, saveFilters, withoutFilter, withoutFilters))
    await mount()
    state.mode.value = 'unread'
    await nextTick()
    while (state.loading.value) await new Promise(resolve => setImmediate(resolve))
    assert.equal(state.rows.value[0].unread, 2)
    const initial = loads
    for (const [method, values] of [
      ['inbox.update', { contact: 'contact', last_read: 'message' }],
      ['message_reads.mark', { contact: 'contact', messages: '["message"]' }],
      ['business_inbox.mark_visible', { doctype: 'Customer', name: 'customer', messages: '["message"]' }],
    ]) {
      await coreApi(method, values, true)
      await refreshed
      assert.deepEqual(state.rows.value, [])
    }
    assert.equal(loads, initial + 3)
    await coreApi('inbox.update', { contact: 'contact' }, true)
    assert.equal(loads, initial + 3, 'Presence-only updates must not cause refresh loops')
    fail = true
    await assert.rejects(coreApi('inbox.update', { contact: 'contact', last_read: 'wrong-message' }, true), /another contact/)
    assert.equal(loads, initial + 3)
  } finally {
    off?.(); scope.stop()
    globalThis.fetch = originalFetch; globalThis.window = originalWindow
  }
})
