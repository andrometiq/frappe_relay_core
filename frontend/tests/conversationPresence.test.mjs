import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { effectScope, nextTick, reactive, ref, watch } from 'vue'

async function presence(props, api) {
  const source = await readFile(new URL('../src/composables/useConversationPresence.js', import.meta.url), 'utf8')
  const body = source.replace(/^import .*\n/gm, '').replace('export function', 'function')
  const mounted = [], unmounted = []
  const make = new Function('useRealtimeRefresh', 'watchRoom', 'subscribeRoom', 'watchDocumentViewers', 'ref', 'watch', 'onMounted', 'onBeforeUnmount', 'coreApi',
    body + '\nreturn useConversationPresence;')
  const use = make(() => {}, watch, () => () => {}, () => () => {}, ref, watch, fn => mounted.push(fn), fn => unmounted.push(fn), api)
  const scope = effectScope()
  scope.run(() => use(props, () => {}))
  mounted.forEach(fn => fn())
  return () => { unmounted.forEach(fn => fn()); scope.stop() }
}

function deferred() {
  let resolve
  const promise = new Promise(ok => { resolve = ok })
  return { promise, resolve }
}

test('messages that become visible while a read is running are marked when it ends', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const original = { document: globalThis.document, window: globalThis.window }
  globalThis.document = { visibilityState: 'visible', hasFocus: () => true, getElementById: () => null }
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
  t.after(() => { globalThis.document = original.document; globalThis.window = original.window })
  const marks = [], first = deferred()
  const api = async (method, values) => {
    if (method === 'message_reads.mark') {
      marks.push(JSON.parse(values.messages))
      if (marks.length === 1) await first.promise
      return {}
    }
    if (method === 'inbox.update') return { last_read: values.last_read || '' }
    return { users: [] }
  }
  const props = reactive({ contact: 'RELAY-CON-0000000001', visibleMessages: ['RELAY-MSG-0000000001'], lastVisible: 'RELAY-MSG-0000000001' })
  const stop = await presence(props, api)
  assert.deepEqual(marks, [['RELAY-MSG-0000000001']])

  props.visibleMessages = ['RELAY-MSG-0000000001', 'RELAY-MSG-0000000002']
  props.lastVisible = 'RELAY-MSG-0000000002'
  await nextTick()
  t.mock.timers.tick(1200)
  await Promise.resolve()
  assert.equal(marks.length, 1, 'The first read is still running')

  first.resolve()
  for (let i = 0; i < 10; i++) await Promise.resolve()
  t.mock.timers.tick(0)
  for (let i = 0; i < 10; i++) await Promise.resolve()
  assert.deepEqual(marks, [['RELAY-MSG-0000000001'], ['RELAY-MSG-0000000002']])
  stop()
})
