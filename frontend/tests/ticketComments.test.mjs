import test from 'node:test'
import assert from 'node:assert/strict'
import { ticketCommentsStore } from '../src/services/ticketComments.js'

const memory = new Map()
globalThis.sessionStorage = { getItem: key => memory.get(key) ?? null, setItem: (key, value) => memory.set(key, value), removeItem: key => memory.delete(key) }

function deferred() {
  let resolve, reject
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}

function fakeApi() {
  const calls = [], pending = []
  const api = (method, values) => {
    const step = deferred()
    calls.push([method, values]); pending.push(step)
    return step.promise
  }
  return { api, calls, pending }
}

test('a second Add comment while the first is posting sends nothing, even after a live reload finishes', async () => {
  const { api, calls, pending } = fakeApi()
  const store = ticketCommentsStore(api)
  const opened = store.open('TKT-00001'); pending[0].resolve([]); await opened

  const first = store.add('Please call Acme Textiles', [])
  assert.equal(store.sending.value, true)
  const reload = store.load()
  pending[2].resolve([])
  await reload
  assert.equal(store.sending.value, true, 'A live reload must not re-enable the button')
  assert.equal(await store.add('Please call Acme Textiles', []), false)
  assert.deepEqual(calls.map(call => call[0]), ['ticket_tags.comments', 'ticket_tags.add_comment', 'ticket_tags.comments'])

  pending[1].resolve([{ name: 'C1', body: 'Please call Acme Textiles' }])
  assert.equal(await first, true)
  assert.equal(store.sending.value, false)
  assert.deepEqual(store.comments.value.map(row => row.name), ['C1'])
})

test('a reload that started before the comment cannot replace the list with the older version', async () => {
  const { api, pending } = fakeApi()
  const store = ticketCommentsStore(api)
  const opened = store.open('TKT-00001'); pending[0].resolve([]); await opened
  const stale = store.load()
  const added = store.add('Checked with the customer', [])
  pending[2].resolve([{ name: 'C1' }]); await added
  pending[1].resolve([]); await stale
  assert.deepEqual(store.comments.value.map(row => row.name), ['C1'])
})

test('a failed post keeps its request key for the retry, so the server adds the comment once', async () => {
  const { api, calls, pending } = fakeApi()
  const store = ticketCommentsStore(api)
  const opened = store.open('TKT-00001'); pending[0].resolve([]); await opened
  const failed = store.add('Retry me', ['agent@example.com'])
  pending[1].reject(new Error('Bad gateway')); await failed
  assert.equal(store.error.value, 'Bad gateway')
  assert.equal(store.sending.value, false)
  const retried = store.add('Retry me', ['agent@example.com'])
  pending[2].resolve([{ name: 'C1' }]); await retried
  const keys = calls.filter(call => call[0] === 'ticket_tags.add_comment').map(call => call[1].request_key)
  assert.equal(keys.length, 2)
  assert.equal(keys[0], keys[1])
})

test('opening another ticket drops a late answer for the previous one', async () => {
  const { api, pending } = fakeApi()
  const store = ticketCommentsStore(api)
  const opened = store.open('TKT-00001'); pending[0].resolve([]); await opened
  const added = store.add('Old ticket comment', [])
  const other = store.open('TKT-00002')
  assert.equal(store.sending.value, false)
  pending[2].resolve([{ name: 'C9' }]); await other
  pending[1].resolve([{ name: 'C1' }])
  assert.equal(await added, false)
  assert.deepEqual(store.comments.value.map(row => row.name), ['C9'])
})
