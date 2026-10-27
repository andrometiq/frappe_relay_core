import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, nextTick, reactive, ref, watch } from 'vue'
import { useTask } from '../src/composables/useTask.js'
const file = await readFile(new URL('../src/components/messages/ConversationTools.vue', import.meta.url), 'utf8')
const source = file.split('<script setup>')[1].split('</script>')[0].replace(/^import .*\n/gm, '')
const make = new Function('ref', 'computed', 'watch', 'onBeforeUnmount', 'defineProps', 'coreApi', 'useTask', 'useConversationPresence', 'useRealtimeRefresh', 'useChatFolders', 'inject',
  source + '\nreturn {state,menu,moving,update,error};')
const tick = () => new Promise(resolve => setImmediate(resolve))
function fixture(t, capabilities = {folders:true}) {
  const requests = [], props = reactive({contact:'A'}), scope = effectScope()
  let refresh, unmount, presence
  const state = scope.run(() => make(ref, computed, watch, fn => unmount = fn, () => props,
    (method, values) => new Promise((resolve, reject) => requests.push({method,values,resolve,reject})), useTask,
    (_props, callback) => { presence = callback; return {people:ref([])} }, (rooms, kinds, fn) => {
      assert.deepEqual(rooms, []); assert.ok(kinds.includes('inbox')); refresh = fn
    }, () => ({ move: (contact, folder) => new Promise((resolve, reject) => requests.push({method:'move',values:{contact,folder},resolve,reject})) }),
    () => ref(capabilities)))
  t.after(() => { unmount(); scope.stop() })
  return {state, requests, props, refresh, presence}
}

test('the chat header has no assignment control', () => {
  assert.doesNotMatch(file, /Assign|assignment|teams\.assign/)
})

test('the menu moves into a folder and removes from the current folder', async t => {
  const {state, requests, presence} = fixture(t)
  requests[0].resolve({}); await tick()
  const labels = () => state.menu.value.map(item => item.label)
  assert.ok(labels().includes('Move to folder')); assert.ok(!labels().includes('Remove from folder'))
  state.menu.value.find(item => item.label === 'Move to folder').onClick()
  assert.equal(state.moving.value, true)
  presence({folder:'F1'})
  state.menu.value.find(item => item.label === 'Remove from folder').onClick()
  assert.deepEqual(requests[1].values, {contact:'A', folder:''})
  requests[1].resolve({folder:null}); await tick()
  assert.equal(state.state.value.folder, null); assert.ok(!labels().includes('Remove from folder'))
})

test('a late read cannot overwrite a different contact', async t => {
  const {state, requests, props, refresh} = fixture(t)
  requests[0].resolve({starred:0}); await tick()
  const stale = refresh()
  props.contact = 'B'; await nextTick()
  requests[2].resolve({starred:1}); await tick()
  requests[1].resolve({starred:0, folder:'Old'}); await stale
  assert.deepEqual(state.state.value, {starred:1})
})

test('losing access clears the star and folder state', async t => {
  const {state, requests, refresh} = fixture(t)
  requests[0].resolve({starred:1, folder:'F1'}); await tick()
  const live = refresh({kinds:new Set(['permissions'])})
  requests[1].reject(Object.assign(Error('Denied'), {status:403})); await live
  assert.deepEqual(state.state.value, {}); assert.equal(state.error.value, 'Denied')
})

test('with folders off the menu has no folder items', async t => {
  const {state, requests} = fixture(t, {folders:false})
  requests[0].resolve({folder:'F1'}); await tick()
  assert.ok(!state.menu.value.some(item => /folder/i.test(item.label)))
})
