import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, reactive, ref, watch } from 'vue'
import { coreApi, frappeRequest } from '../src/services/coreApi.js'
import { useStoredDraft } from '../src/composables/useStoredDraft.js'
import { addressList, channelStatus, compositionScope, emailComposition } from '../src/services/channelComposition.js'

const source = (await readFile(new URL('../src/components/messages/EmailComposer.vue', import.meta.url), 'utf8'))
  .split('<script setup>')[1].split('</script>')[0].replace(/^import .*\n/gm, '')
const make = new Function('computed', 'reactive', 'ref', 'watch', 'inject', 'onMounted', 'onBeforeUnmount', 'messagesKey',
  'coreApi', 'randomUUID', 'addressList', 'channelStatus', 'compositionScope', 'emailComposition', 'useStoredDraft', 'useRealtimeRefresh',
  source + '\nreturn {draft,send,recover,check,locked,error};')
function fixture(t, respond) {
  const previous = Object.fromEntries(['fetch', 'window', 'document', 'sessionStorage'].map(key => [key, globalThis[key]]))
  const storage = new Map(), calls = [], scopes = [], bubbles = new Map()
  let uuid = 0
  globalThis.window = {frappe:{csrf_token:'local-test-token'}}
  globalThis.document = {getElementById:() => ({dataset:{user:'local-user'}})}
  globalThis.sessionStorage = {getItem:key => storage.get(key), setItem:(key, value) => storage.set(key, value), removeItem:key => storage.delete(key)}
  globalThis.fetch = async (url, options) => {
    const method = url.split('relay_core.')[1].split('?')[0]
    const values = options.method === 'POST' ? JSON.parse(options.body) : Object.fromEntries(new URL(url, 'http://local.invalid').searchParams)
    calls.push({method, values, verb:options.method})
    return respond(method, values)
  }
  const anchor = {name:'email-1',channel:'email-channel',sender_endpoint:'sender@example.invalid',
    business_doctype:'Customer',business_name:'local-customer',provider_context:{provider:'Email'},message_data:{email:{subject:'Order 25'}}}
  function mount() {
    const scope = effectScope(); scopes.push(scope)
    let mounted
    const state = scope.run(() => make(computed, reactive, ref, watch, () => ({source:ref(anchor),busy:ref(false),
      beginEmail:(_anchor, _values, key) => {
        if (!bubbles.has(key)) bubbles.set(key, {})
        return bubbles.get(key)
      }, finishEmail:async () => {}}), fn => mounted = fn, () => {}, Symbol(), coreApi, () => 'request-' + ++uuid,
      addressList, channelStatus, compositionScope, emailComposition, useStoredDraft, () => {}))
    return {...state, mounted, unmount:() => scope.stop()}
  }
  t.after(() => { scopes.forEach(scope => scope.stop()); Object.assign(globalThis, previous) })
  return {mount, calls, bubbles}
}
const rejected = (status, exc_type) => Response.json({exc_type, exc:'private traceback', _server_messages:JSON.stringify([{message:'Review recipient'}])}, {status})

for (const [status, type] of [[417,'ValidationError'], [400,'ValueError'], [403,'PermissionError'], [500,'ValueError']]) {
  test(`confirmed pre-admission ${status} ${type} preserves an editable saved draft`, async t => {
    const {mount, calls, bubbles} = fixture(t, method => method === 'email.send' ? rejected(status, type) : Response.json({message:{status:'Unconfirmed'}}))
    const state = mount(); state.draft.body = 'Order quantity 25'
    await state.send()
    assert.equal(state.draft.request.status, 'Rejected')
    assert.equal(state.draft.body, 'Order quantity 25')
    assert.equal(bubbles.get('request-1').status, 'Rejected')
    assert.deepEqual(calls.map(call => [call.method, call.verb]), [['email.send','POST'], ['email.send_status','GET']])
    state.unmount()
    const restored = mount(); await restored.mounted(); await restored.check(); await restored.recover()
    assert.equal(restored.draft.request.status, 'Rejected'); assert.equal(calls.length, 2)
    restored.draft.request = null
    assert.equal(restored.locked.value, false)
    restored.draft.to = 'corrected@example.invalid'
    await restored.send()
    assert.equal(calls[2].values.request_key, 'request-2')
    assert.deepEqual(calls[2].values.to, ['corrected@example.invalid'])
  })
}

for (const outcome of ['network', 'server', 'untyped', 'malformed', 'status-denied']) {
  test(`${outcome} failure retains the uncertain request and recovery key`, async t => {
    const {mount, calls} = fixture(t, method => {
      if (method === 'email.send_status') return rejected(403, 'PermissionError')
      if (outcome === 'network') throw Error('Offline')
      if (outcome === 'malformed') return new Response('invalid JSON', {status:200})
      return rejected(outcome === 'server' ? 500 : 417, outcome === 'untyped' ? undefined : outcome === 'server' ? 'RuntimeError' : 'ValueError')
    })
    const state = mount(); state.draft.body = 'Order quantity 25'
    await state.send(); const key = state.draft.request.key
    assert.equal(state.draft.request.status, 'Uncertain'); assert.equal(state.locked.value, true)
    await state.recover()
    assert.equal(state.draft.request.key, key)
    assert.ok(calls.filter(call => call.method === 'email.send').every(call => call.values.request_key === key))
    assert.equal(state.draft.body, 'Order quantity 25')
  })
}

test('an admitted attempt uses its journal status instead of unlocking', async t => {
  const {mount, bubbles} = fixture(t, method => method === 'email.send' ? rejected(417, 'ValueError')
    : Response.json({message:{status:'Queued',action:'email-action'}}))
  const state = mount(); state.draft.body = 'Order quantity 25'
  await state.send()
  assert.equal(state.draft.request.action, 'email-action'); assert.equal(state.draft.request.status, 'Queued')
  assert.equal(state.locked.value, true); assert.equal(bubbles.get('request-1').status, 'Queued')
})

test('recovery resolves a prior network failure to a confirmed rejection with the same key', async t => {
  let sends = 0
  const {mount, calls} = fixture(t, method => {
    if (method === 'email.send' && !sends++) throw Error('Offline')
    return method === 'email.send' ? rejected(417, 'ValidationError') : Response.json({message:{status:'Unconfirmed'}})
  })
  const state = mount(); state.draft.body = 'Order quantity 25'
  await state.send(); await state.recover()
  assert.equal(state.draft.request.status, 'Rejected')
  assert.equal(calls[0].values.request_key, calls[1].values.request_key)
})

test('HTTP wrapper returns the message shape and retains safe denial metadata', async t => {
  const previous = globalThis.fetch
  t.after(() => globalThis.fetch = previous)
  globalThis.fetch = async () => Response.json({message:{items:[{name:'local-record'}]}})
  assert.deepEqual(await frappeRequest('fixture.read'), {items:[{name:'local-record'}]})
  for (const status of [401,403,417,500]) {
    globalThis.fetch = async () => rejected(status, 'ValidationError')
    await assert.rejects(coreApi('fixture.read'), error => {
      assert.equal(error.status, status); assert.equal(error.exceptionType, 'ValidationError')
      assert.doesNotMatch(error.message, /private traceback/)
      if (status === 401) assert.match(error.message, /session has expired/)
      else assert.equal(error.message, 'Review recipient')
      return true
    })
  }
  globalThis.fetch = async () => Response.json({exc:'private traceback', exc_type:'ValueError'})
  await assert.rejects(frappeRequest('fixture.read'), error => error.status === 200 && error.exceptionType === 'ValueError')
})
