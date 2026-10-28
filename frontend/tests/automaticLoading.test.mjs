import test from 'node:test'
import assert from 'node:assert/strict'
import { effectScope, nextTick, ref } from 'vue'
import { useLoadMore } from '../src/composables/useLoadMore.js'
import { useDebouncedSearch } from '../src/composables/useDebouncedSearch.js'

const settle = async () => { await nextTick(); await nextTick(); await nextTick() }
function observers(t) {
  const original = globalThis.IntersectionObserver, instances = []
  globalThis.IntersectionObserver = class {
    constructor(callback, options) { this.callback = callback; this.options = options; this.live = true; instances.push(this) }
    observe(node) { this.node = node }
    disconnect() { this.live = false }
  }
  t.after(() => { globalThis.IntersectionObserver = original })
  return { instances, current: () => instances.findLast(row => row.live) }
}

test('sentinel serializes requests, re-observes short pages, stops at last page and disconnects', async t => {
  const io = observers(t), scope = effectScope(), loading = ref(false), hasMore = ref(true)
  let requests = 0, finish
  const sentinel = scope.run(() => useLoadMore({ loading, hasMore, load: async () => {
    requests++; loading.value = true
    await new Promise(resolve => finish = resolve)
    if (requests === 2) hasMore.value = false
    loading.value = false
  }}))
  sentinel.value = {}; await settle()
  const first = io.current(), pending = first.callback([{isIntersecting:true}])
  first.callback([{isIntersecting:true}]); assert.equal(requests, 1)
  finish(); await pending; await settle()
  assert.notEqual(io.current(), first)
  const last = io.current().callback([{isIntersecting:true}]); finish(); await last; await settle()
  assert.equal(requests, 2); assert.equal(io.current(), undefined)
  scope.stop(); assert.ok(io.instances.every(row => !row.live))
})

test('failed page stops automatic retries and prepending retains the scroll position', async t => {
  const io = observers(t), scope = effectScope(), error = ref(''), root = ref({scrollTop:15, scrollHeight:400})
  let calls = 0
  const sentinel = scope.run(() => useLoadMore({ loading: ref(false), hasMore: ref(true), error, root, preserveScroll: true, load: async () => {
    if (++calls === 1) error.value = 'Offline'
    else root.value.scrollHeight += 250
  }}))
  sentinel.value = {}; await settle()
  await io.current().callback([{isIntersecting:true}]); await settle()
  assert.equal(io.current(), undefined); assert.equal(root.value.scrollTop, 15)
  error.value = ''; await settle()
  await io.current().callback([{isIntersecting:true}]); await settle()
  assert.equal(root.value.scrollTop, 265)
  scope.stop(); assert.ok(io.instances.every(row => !row.live))
})

test('typing fires one search after 300 ms; Enter flushes it and unmount cancels it', async t => {
  t.mock.timers.enable({apis:['setTimeout']})
  const scope = effectScope(), query = ref(''), calls = [], invalidated = []
  const enter = scope.run(() => useDebouncedSearch(query, () => calls.push(query.value), () => invalidated.push(query.value)))
  query.value = 'A'; await nextTick(); t.mock.timers.tick(100)
  query.value = 'As'; await nextTick(); t.mock.timers.tick(100)
  query.value = 'Asha'; await nextTick(); t.mock.timers.tick(299)
  assert.deepEqual(calls, []); t.mock.timers.tick(1); assert.deepEqual(calls, ['Asha'])
  query.value = 'Ravi'; await nextTick(); enter(); t.mock.timers.tick(300)
  assert.deepEqual(calls, ['Asha', 'Ravi'])
  query.value = 'Cancelled'; await nextTick(); scope.stop(); t.mock.timers.tick(300)
  assert.equal(calls.length, 2); assert.equal(invalidated.length, 5)
})
