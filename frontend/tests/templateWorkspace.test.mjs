import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, ref } from 'vue'

const workspaceSource = (await readFile(new URL('../src/composables/whatsapp/useWhatsAppTemplatesWorkspace.js', import.meta.url), 'utf8'))
  .replace(/^import .*\n/gm, '').replace('export function', 'function')
const makeWorkspace = new Function('computed','ref','onMounted','useRealtimeRefresh','coreApi','templateParameterDescriptors',workspaceSource+'\nreturn useWhatsAppTemplatesWorkspace();')

test('the template list reads the local copy with the connection and the Hub capabilities together', async t => {
  const scope = effectScope();t.after(() => scope.stop())
  const calls = [], answers = {
    'whatsapp.connection': {configured:true}, capabilities: {templates:true},
    'whatsapp_templates.directory': {data:[{id:'1',name:'order_update'}],sync:{synced_at:null,templates:1,syncing:true}},
  }
  const workspace = scope.run(() => makeWorkspace(computed,ref,()=>{},()=>{},async(method,values) => {
    const key = method === 'whatsapp.execute' ? values.operation : method
    calls.push(key)
    return answers[key]
  },()=>[]))
  await workspace.refresh()
  assert.deepEqual(calls, ['capabilities', 'whatsapp.connection', 'whatsapp_templates.directory'], 'No Hub template list on open')
  assert.deepEqual(workspace.templates.value.map(row => row.name), ['order_update'])
  assert.equal(workspace.syncStatus.value.syncing, true)
  assert.equal(workspace.supported.value, true)
})

test('templates show before a slow Hub capabilities read finishes', async t => {
  const scope = effectScope();t.after(() => scope.stop())
  let answerHub
  const workspace = scope.run(() => makeWorkspace(computed,ref,()=>{},()=>{},async(method,values) => {
    if (method === 'whatsapp.execute') return new Promise(resolve => answerHub = resolve)
    return method === 'whatsapp.connection' ? {configured:true} : {data:[{id:'1',name:'order_update'}],sync:{}}
  },()=>[]))
  await workspace.refresh()
  assert.deepEqual(workspace.templates.value.map(row => row.name), ['order_update'])
  assert.equal(workspace.busy.value, false)
  answerHub({templates:false}); await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(workspace.templates.value, [], 'An account without templates still shows none')
})

test('an unconfigured account shows no templates even though the Hub capabilities read fails', async t => {
  const scope = effectScope();t.after(() => scope.stop())
  const workspace = scope.run(() => makeWorkspace(computed,ref,()=>{},()=>{},async(method) => {
    if (method === 'whatsapp.execute') throw Error('Hub could not complete this operation')
    return {configured:false}
  },()=>[]))
  await workspace.refresh()
  assert.equal(workspace.capabilities.value, null)
  assert.equal(workspace.error.value, '')
})
