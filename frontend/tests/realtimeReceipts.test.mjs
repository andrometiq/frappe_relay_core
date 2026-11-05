import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'
import { isReceiptsOnly, listRefresh } from '../src/services/realtimeRefreshQueue.js'

const stub = source => 'data:text/javascript,' + encodeURIComponent(source)
register(stub(`const socket = ${JSON.stringify(stub('export const io = () => globalThis.fakeSocket'))}
export async function resolve(specifier, context, next) {
  if (specifier === 'socket.io-client') return { url: socket, shortCircuit: true }
  if (context.parentURL?.includes('/src/') && /^\\.\\.?\\//.test(specifier) && !/\\.\\w+$/.test(specifier)) return next(specifier + '.js', context)
  return next(specifier, context)
}`))

test('a delivery receipt reaches a view that lists receipts under its own kind, and others as a message change', async t => {
  const { watchRealtime } = await import('../src/composables/useRealtimeRefresh.js')
  const { startRealtime } = await import('../src/services/realtime.js')
  const handlers = {}, previous = { document: globalThis.document, location: globalThis.location }
  globalThis.fakeSocket = { connected: true, on: (name, fn) => { handlers[name] = fn }, emit() {} }
  globalThis.document = { visibilityState: 'visible', addEventListener() {}, removeEventListener() {},
    getElementById: () => ({ dataset: { site: 'local.test' } }) }
  globalThis.location = { origin: 'http://127.0.0.1', port: '' }
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const lists = [], threads = []
  const stops = [watchRealtime([], ['messages', 'receipts'], ({ kinds }) => lists.push([...kinds]), 10),
    watchRealtime([], ['messages'], ({ kinds, messages }) => threads.push([[...kinds], [...messages]]), 10)]
  t.after(() => { stops.forEach(stop => stop()); Object.assign(globalThis, previous) })
  await startRealtime()
  handlers.relay_changed({ kind: 'messages', messages: ['RELAY-MSG-0000000001'], receipt: 1 })
  t.mock.timers.tick(10); await Promise.resolve()
  assert.deepEqual(lists, [['receipts']])
  assert.deepEqual(threads, [[['messages'], ['RELAY-MSG-0000000001']]])
  assert.equal(isReceiptsOnly(new Set(lists[0])), true)
  assert.equal(listRefresh(new Set(lists[0])), 'none')
  handlers.relay_changed({ kind: 'messages' })
  t.mock.timers.tick(10); await Promise.resolve()
  assert.deepEqual(lists.at(-1), ['messages'])
  assert.equal(isReceiptsOnly(new Set(['receipts', 'messages'])), false)
})
