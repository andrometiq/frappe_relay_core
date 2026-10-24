import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, nextTick, reactive, ref, watch } from 'vue'
import { useTask } from '../src/composables/useTask.js'
const source = (await readFile(new URL('../src/components/messages/ConversationTools.vue', import.meta.url), 'utf8'))
  .split('<script setup>')[1].split('</script>')[0].replace(/^import .*\n/gm, '')
const make = new Function('ref', 'computed', 'watch', 'onBeforeUnmount', 'defineProps', 'coreApi', 'useTask', 'useConversationPresence', 'useRealtimeRefresh',
  source + '\nreturn {team,agent,folder,state,assign,update,assignmentChanged,error};')
const tick = () => new Promise(resolve => setImmediate(resolve))
function fixture(t) {
  const requests = [], props = reactive({contact:'A'}), scope = effectScope()
  let refresh, unmount, presence
  const state = scope.run(() => make(ref, computed, watch, fn => unmount = fn, () => props,
    (method, values) => new Promise((resolve, reject) => requests.push({method,values,resolve,reject})), useTask,
    (_props, callback) => { presence = callback; return {people:ref([])} }, (rooms, kinds, fn) => {
      assert.deepEqual(rooms, ['Relay Conversation Assignment']); assert.ok(kinds.includes('inbox')); refresh = fn
    }))
  t.after(() => { unmount(); scope.stop() })
  return {state, requests, props, refresh, unmount, presence}
}
const assignment = (team, agent) => ({can_assign:true, assignment:{team, assigned_to:agent}})

test('presence before the initial read initializes the folder and Save preserves it', async t => {
  const {state, requests, presence} = fixture(t)
  presence({folder:'Follow up',unread:2})
  requests[0].resolve({...assignment('Sales','alice'),folder:'Follow up'}); await tick()
  assert.equal(state.folder.value,'Follow up')
  const saved = state.update({folder:state.folder.value})
  assert.deepEqual(requests[1].values,{contact:'A',folder:'Follow up'})
  requests[1].resolve({folder:'Follow up'}); await saved
  presence({folder:'New folder'})
  assert.equal(state.folder.value,'New folder')
})

test('folder edits survive presence, initial read and save responses', async t => {
  const {state, requests, presence, refresh} = fixture(t)
  state.folder.value = 'Local edit'
  presence({folder:'Server folder'})
  requests[0].resolve({folder:'Server folder'}); await tick()
  assert.equal(state.folder.value,'Local edit')
  const saved = state.update({folder:state.folder.value})
  state.folder.value = 'Next edit'
  requests[1].resolve({folder:'Local edit'}); await saved
  assert.equal(state.folder.value,'Next edit')
  state.folder.value = ''
  const live = refresh()
  requests[2].resolve({folder:'Server folder'}); await live
  assert.equal(state.folder.value,'','Explicitly clearing the folder is an edit')
})

test('socket and reconnect refresh assignment fields while preserving local edits', async t => {
  const {state, requests, refresh} = fixture(t)
  requests[0].resolve(assignment('Sales', 'alice')); await tick()
  const live = refresh({kinds:new Set(['inbox'])})
  requests[1].resolve(assignment('Support', 'bob')); await live
  assert.equal(state.team.value, 'Support'); assert.equal(state.agent.value, 'bob')
  state.agent.value = 'local-agent'; state.folder.value = 'Unfinished folder'
  const reconnected = refresh({kinds:new Set(['reconnect'])})
  requests[2].resolve(assignment('Accounts', 'carol')); await reconnected
  assert.equal(state.team.value, 'Support'); assert.equal(state.agent.value, 'local-agent')
  assert.equal(state.assignmentChanged.value, true)
  assert.equal(state.folder.value, 'Unfinished folder')
  const saved = state.assign()
  assert.deepEqual(requests[3].values, {contact:'A', team:'Support', assigned_to:'local-agent'})
  requests[3].resolve({}); await tick()
  requests[4].resolve(assignment('Support', 'local-agent')); await saved
  assert.equal(state.assignmentChanged.value, false)
  const later = refresh()
  requests[5].resolve(assignment('New team', 'dave')); await later
  assert.equal(state.team.value, 'New team')
})

test('late refreshes and saves cannot overwrite a different contact or an unmounted view', async t => {
  const {state, requests, props, refresh, unmount} = fixture(t)
  requests[0].resolve(assignment('Sales', 'alice')); await tick()
  const oldRefresh = refresh(), oldSave = state.assign()
  props.contact = 'B'; await nextTick()
  requests[3].resolve(assignment('Support', 'bob')); await tick()
  requests[1].resolve(assignment('Stale', 'stale')); await oldRefresh
  requests[2].resolve({}); await oldSave
  assert.equal(state.team.value, 'Support'); assert.equal(state.agent.value, 'bob')
  assert.equal(requests.length, 4)
  const pending = refresh(); unmount()
  requests[4].resolve(assignment('Unmounted', 'stale')); await pending
  assert.equal(state.team.value, 'Support')
})

test('permission refresh clears assignment fields and disables assignment controls', async t => {
  const {state, requests, refresh} = fixture(t)
  requests[0].resolve(assignment('Sales', 'alice')); await tick()
  state.agent.value = 'unsaved'
  const live = refresh({kinds:new Set(['permissions'])})
  requests[1].reject(Object.assign(Error('Denied'), {status:403})); await live
  assert.equal(state.team.value, ''); assert.equal(state.agent.value, '')
  assert.equal(state.state.value.can_assign, undefined); assert.equal(state.error.value, 'Denied')
})

test('a save completing after switching away and back cannot reset the new draft', async t => {
  const {state, requests, props} = fixture(t)
  requests[0].resolve(assignment('Sales', 'alice')); await tick()
  const saved = state.assign()
  props.contact = 'B'; await nextTick(); props.contact = 'A'; await nextTick()
  requests[2].resolve(assignment('Other', 'bob'))
  requests[3].resolve(assignment('Current', 'carol')); await tick()
  state.agent.value = 'New local edit'
  requests[1].resolve({}); await saved
  assert.equal(state.team.value, 'Current'); assert.equal(state.agent.value, 'New local edit')
  assert.equal(requests.length, 4)
})
