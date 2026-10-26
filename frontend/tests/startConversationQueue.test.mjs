import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {ref,computed,watch,effectScope} from 'vue'
import {sha256Hex} from '../src/services/crypto.js'
import {useStoredDraft} from '../src/composables/useStoredDraft.js'
import {channelCan} from '../src/services/enabledChannels.js'
import {whatsappCapabilities} from './channelCapabilities.js'
// Telegram and Email stay off in v1; these tests still cover their start paths.
const inject=()=>ref({...whatsappCapabilities,channels:{...whatsappCapabilities.channels,Email:{email_threading:true}}})
import {templateParameterDescriptors,buildTemplateComponents} from '../src/services/templateParameters.js'
const source=(await readFile(new URL('../src/components/messages/StartConversation.vue',import.meta.url),'utf8')).split('<script setup>')[1].split('</script>')[0].replace(/^import [\s\S]*?from ["'][^"']+["'];/gm,'')
const make=new Function('ref','computed','watch','onMounted','onBeforeUnmount','defineProps','defineEmits','coreApi','sha256Hex','randomUUID','templateParameterDescriptors','buildTemplateComponents','sessionStorage','AbortController','setTimeout','clearTimeout','useEnabledChannels','useStoredDraft','inject','channelCan',source+'\nreturn {send,body,subject,parameters,endpoint,endpoints,pending,shown,editRejected,templates,templateId,kind,loadTemplates};')
for(const status of ['Queued','Submitted','Uncertain'])test(`conversation start ${status}`,async()=>{
 const events=[],calls=[],storage=new Map()
 const state=make(ref,computed,watch,()=>{},()=>{},()=>({contact:'contact'}),()=> (...args)=>events.push(args),async(method,args)=>{calls.push({method,args});return {status,action:'action',message:null}},()=> 'digest',()=> 'stable-request-key',()=> [],()=> [],{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},AbortController,setTimeout,clearTimeout,()=>()=>true,()=>()=>{},inject,channelCan)
 state.endpoints.value=[{value:'endpoint',provider:'Telegram'}];state.endpoint.value='endpoint';state.body.value='Hello'
 await state.send()
 assert.equal(calls.length,1)
 if(status==='Uncertain'){assert.equal(state.shown.value,true);assert.equal(state.pending.value.action,'action');assert.equal(storage.size,1);assert.ok(!events.some(e=>e[0]==='sent'))}
 else {assert.equal(storage.size,0);assert.equal(state.shown.value,false);assert.ok(events.some(e=>e[0]==='sent'&&e[1].status===status))}
})

for (const reconcile of [false, true]) test(`old template draft renews its actual key after reopening (${reconcile ? 'reconciled' : 'direct'})`, async t => {
 const previous = {sessionStorage:globalThis.sessionStorage,document:globalThis.document}
 const memory = new Map(), calls = [], scopes = []
 let keys = 0, failSend = false
 globalThis.document = {getElementById:()=>({dataset:{user:'local-user'}})}
 globalThis.sessionStorage = {getItem:key=>memory.get(key),setItem:(key,value)=>memory.set(key,value),removeItem:key=>memory.delete(key)}
 t.after(()=>{scopes.forEach(scope=>scope.stop());Object.assign(globalThis,previous)})
 const template = {id:'quantity',name:'order_quantity',language:'en_US',status:'APPROVED',components:[{type:'BODY',text:'Quantity {{1}}'}]}
 const api = async (method,args) => {
   calls.push({method,args})
   if (method === 'whatsapp.execute') return {data:[template]}
   if (failSend) throw Error('Connection lost')
   return {status:'Rejected',action:'rejected-action'}
 }
 function mount() {
   const scope = effectScope(); scopes.push(scope)
   const state = scope.run(()=>make(ref,computed,watch,()=>{},()=>{},()=>({contact:'contact',businessDoctype:'Customer',businessName:'local-customer'}),()=>()=>{},api,
     sha256Hex,()=> 'request-'+ ++keys,templateParameterDescriptors,buildTemplateComponents,sessionStorage,AbortController,setTimeout,clearTimeout,()=>()=>true,useStoredDraft,inject,channelCan))
   state.endpoints.value = [{value:'endpoint',channel:'channel',provider:'WhatsApp',window:{open:false}}]
   state.endpoint.value = 'endpoint'
   return {...state,unmount:()=>scope.stop()}
 }
 const first = mount()
 await first.loadTemplates()
 first.parameters.value = {'BODY:0:1':'25'}
 await first.send()
 const original = calls.at(-1).args
 const storage = first.pending.value.storage
 assert.equal(memory.get(storage),original.request_key)
 // Simulate the persisted format before pending.storage was introduced.
 first.pending.value = {status:reconcile ? 'Uncertain' : 'Rejected',action:'rejected-action'}
 first.unmount()
 const reopened = mount()
 assert.equal(reopened.templates.value.length,0)
 if (reconcile) await reopened.send()
 reopened.editRejected()
 assert.equal(reopened.pending.value,null)
 assert.deepEqual(reopened.parameters.value,{'BODY:0:1':'25'})
 reopened.unmount()
 const edited = mount()
 await edited.send()
 assert.equal(memory.get(storage),original.request_key,'Missing template metadata cannot reset an unrelated payload key')
 await edited.loadTemplates()
 failSend = true
 await edited.send()
 const retry = calls.at(-1).args
 assert.deepEqual(retry.data,original.data)
 assert.notEqual(retry.request_key,original.request_key)
 assert.equal(memory.get(storage),retry.request_key)
 await edited.send()
 assert.equal(calls.at(-1).args.request_key,retry.request_key,'An unknown outcome retains the renewed key')
})

for (const viaReconcile of [false, true]) test(`rejected start can be edited and retried with a fresh key (${viaReconcile ? 'reconciled' : 'direct'})`, async () => {
 const memory = new Map(), calls = []; let keys = 0, restore
 const state = make(ref,computed,watch,()=>{},()=>{},()=>({contact:'contact',businessDoctype:'Customer',businessName:'local-customer'}),()=>()=>{},async(method,args)=>{
   calls.push({method,args})
   return {status:viaReconcile && calls.length === 1 ? 'Uncertain' : 'Rejected',action:'rejected-action'}
 },sha256Hex,()=> 'request-'+ ++keys,()=> [],()=> [],{getItem:key=>memory.get(key),setItem:(key,value)=>memory.set(key,value),removeItem:key=>memory.delete(key)},AbortController,setTimeout,clearTimeout,()=>()=>true,(_scope,_read,write)=>{restore=write;return ()=>{}},inject,channelCan)
 state.endpoints.value=[{value:'endpoint',channel:'channel',provider:'Email'}];state.endpoint.value='endpoint'
 state.body.value='Order quantity 25';state.subject.value='Order';state.parameters.value={number:'25'}
 await state.send()
 if (viaReconcile) {
   state.editRejected(); assert.equal(state.pending.value.status,'Uncertain')
   await state.send(); assert.equal(calls[1].method,'messaging.reconcile')
 }
 assert.equal(state.pending.value.status,'Rejected')
 const saved=JSON.parse(JSON.stringify({body:state.body.value,subject:state.subject.value,parameters:state.parameters.value,pending:state.pending.value}))
 restore(saved)
 const count=calls.length;await state.send();assert.equal(calls.length,count,'Rejected is terminal')
 state.editRejected()
 assert.equal(state.pending.value,null);assert.equal(state.body.value,'Order quantity 25');assert.equal(state.subject.value,'Order')
 assert.deepEqual(state.parameters.value,{number:'25'});assert.equal(memory.size,0)
 await state.send()
 assert.notEqual(calls.at(-1).args.request_key,calls[0].args.request_key)
 assert.equal(calls.at(-1).args.business_doctype,'Customer');assert.equal(calls.at(-1).args.business_name,'local-customer')
})
