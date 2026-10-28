import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { effectScope, nextTick, ref } from 'vue'
import { useDebouncedSearch } from '../src/composables/useDebouncedSearch.js'
import { useLoadMore } from '../src/composables/useLoadMore.js'

const text = await readFile(new URL('../src/components/UnlinkedContacts.vue', import.meta.url), 'utf8')
const script = text.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*\n/gm, '')
const factory = new Function('ref', 'onMounted', 'onBeforeUnmount', 'useRealtimeRefresh', 'coreApi', 'useDebouncedSearch', 'useLoadMore',
  script + '\nreturn { rows, query, next, busy, error, more, load, linked, selected };')

function setup(api) {
  let mount, cleanup, refresh, intersection, timer
  const scope = effectScope(), observed = []
  class Observer {
    constructor(callback) { intersection = callback }
    observe(element) { observed.push(element) }
    disconnect() {}
  }
  const globals = { IntersectionObserver: globalThis.IntersectionObserver, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout }
  Object.assign(globalThis, { IntersectionObserver: Observer, setTimeout: fn => { timer = fn; return 1 }, clearTimeout: () => { timer = null } })
  const state = scope.run(() => factory(ref, fn => { mount = fn }, fn => { cleanup = fn },
    (_dt, _kinds, fn) => { refresh = fn }, api, useDebouncedSearch, useLoadMore))
  return { state, mount, refresh, observed, intersect: () => intersection([{ isIntersecting: true }]),
    search: () => timer?.(), stop: () => { cleanup(); scope.stop(); Object.assign(globalThis, globals) } }
}

const flush = async () => { await nextTick(); await Promise.resolve(); await nextTick() }

test('contact sentinel appends pages and linking refreshes the remaining queue', async () => {
  const calls = []
  const fixture = setup(async (method, args) => {
    calls.push([method, args])
    return args.after ? { items: [{ name: 'R2' }], next: null } : { items: [{ name: 'R1' }], next: { after: 'R1', before: 'date' } }
  })
  try {
    await fixture.mount()
    fixture.state.more.value = {}
    await flush()
    fixture.intersect()
    await flush()
    assert.deepEqual(fixture.state.rows.value.map(row => row.name), ['R1', 'R2'])
    assert.deepEqual(calls[1], ['contacts.unlinked', { query: '', after: 'R1', before: 'date' }])
    fixture.state.selected.value = 'Person'
    fixture.state.linked()
    await flush()
    assert.equal(fixture.state.selected.value, '')
    assert.equal(fixture.state.rows.value.length, 1)
  } finally { fixture.stop() }
})

test('search discards an older response and only requests the latest typed query', async () => {
  let resolveOld
  const calls = []
  const fixture = setup(async (_method, args) => {
    calls.push(args)
    if (!args.query) return new Promise(resolve => { resolveOld = resolve })
    return { items: [{ name: 'matching' }], next: null }
  })
  try {
    const old = fixture.mount()
    fixture.state.query.value = '79'
    await flush()
    fixture.state.query.value = '7976'
    await flush()
    await fixture.search()
    resolveOld({ items: [{ name: 'stale' }], next: { after: 'stale' } })
    await old
    assert.deepEqual(calls.map(row => row.query), ['', '7976'])
    assert.deepEqual(fixture.state.rows.value, [{ name: 'matching' }])
    assert.equal(fixture.state.next.value, null)
  } finally { fixture.stop() }
})

test('pagination failure preserves loaded contacts and allows retry', async () => {
  let failed = false
  const fixture = setup(async (_method, args) => {
    if (args.after && !failed) { failed = true; throw Error('Offline') }
    return args.after ? { items: [{ name: 'R2' }], next: null } : { items: [{ name: 'R1' }], next: { after: 'R1', before: 'date' } }
  })
  try {
    await fixture.mount()
    await fixture.state.load(fixture.state.next.value)
    assert.equal(fixture.state.error.value, 'Offline')
    assert.deepEqual(fixture.state.rows.value, [{ name: 'R1' }])
    await fixture.state.load(fixture.state.next.value)
    assert.deepEqual(fixture.state.rows.value.map(row => row.name), ['R1', 'R2'])
    assert.equal(fixture.state.error.value, '')
  } finally { fixture.stop() }
})
