import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, nextTick, reactive, ref, watch } from 'vue'
import { useTask } from '../src/composables/useTask.js'
const source = (await readFile(new URL('../src/components/messages/ConversationTools.vue', import.meta.url), 'utf8'))
  .split('<script setup>')[1].split('</script>')[0].replace(/^import .*\n/gm, '')
const make = new Function('ref', 'computed', 'watch', 'onBeforeUnmount', 'defineProps', 'coreApi', 'useTask', 'useConversationPresence', 'useRealtimeRefresh', 'useChatFolders',
  source + '\nreturn {team,agent,state,menu,moving,assign,update,assignmentChanged,error};')
const tick = () => new Promise(resolve => setImmediate(resolve))
function fixture(t) {
  const requests = [], props = reactive({contact:'A'}), scope = effectScope()
  let refresh, unmount, presence
  const state = scope.run(() => make(ref, computed, watch, fn => unmount = fn, () => props,
    (method, values) => new Promise((resolve, reject) => requests.push({method,values,resolve,reject})), useTask,
    (_props, callback) => { presence = callback; return {people:ref([])} }, (rooms, kinds, fn) => {
      assert.deepEqual(rooms, ['Relay Conversation Assignment']); assert.ok(kinds.includes('inbox')); refresh = fn
    }, () => ({ move: (contact, folder) => new Promise((resolve, reject) => requests.push({method:'move',values:{contact,folder},resolve,reject})) })))
  t.after(() => { unmount(); scope.stop() })
  return {state, requests, props, refresh, unmount, presence}
}
const assignment = (team, agent) => ({can_assign:true, assignment:{team, assigned_to:agent}})

test('the menu moves into a folder and removes from the current folder', async t => {
  const {state, requests, presence} = fixture(t)
  requests[0].resolve(assignment('Sales','alice')); await tick()
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

test('socket and reconnect refresh assignment fields while preserving local edits', async t => {
  const {state, requests, refresh} = fixture(t)
  requests[0].resolve(assignment('Sales', 'alice')); await tick()
  const live = refresh({kinds:new Set(['inbox'])})
  requests[1].resolve(assignment('Support', 'bob')); await live
  assert.equal(state.team.value, 'Support'); assert.equal(state.agent.value, 'bob')
  state.agent.value = 'local-agent'
  const reconnected = refresh({kinds:new Set(['reconnect'])})
  requests[2].resolve(assignment('Accounts', 'carol')); await reconnected
  assert.equal(state.team.value, 'Support'); assert.equal(state.agent.value, 'local-agent')
  assert.equal(state.assignmentChanged.value, true)
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
