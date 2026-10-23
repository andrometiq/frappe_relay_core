import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {ref,computed,watch} from 'vue'
const source=(await readFile(new URL('../src/components/messages/StartConversation.vue',import.meta.url),'utf8')).split('<script setup>')[1].split('</script>')[0].replace(/^import [\s\S]*?from ["'][^"']+["'];/gm,'')
const make=new Function('ref','computed','watch','onMounted','onBeforeUnmount','defineProps','defineEmits','coreApi','sha256Hex','randomUUID','templateParameterDescriptors','buildTemplateComponents','sessionStorage','AbortController','setTimeout','clearTimeout',source+'\nreturn {send,body,endpoint,endpoints,pending,shown};')
for(const status of ['Queued','Submitted','Uncertain'])test(`conversation start ${status}`,async()=>{
 const events=[],calls=[],storage=new Map()
 const state=make(ref,computed,watch,()=>{},()=>{},()=>({contact:'contact'}),()=> (...args)=>events.push(args),async(method,args)=>{calls.push({method,args});return {status,action:'action',message:null}},()=> 'digest',()=> 'stable-request-key',()=> [],()=> [],{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},AbortController,setTimeout,clearTimeout)
 state.endpoints.value=[{value:'endpoint',provider:'Telegram'}];state.endpoint.value='endpoint';state.body.value='Hello'
 await state.send()
 assert.equal(calls.length,1)
 if(status==='Uncertain'){assert.equal(state.shown.value,true);assert.equal(state.pending.value.action,'action');assert.equal(storage.size,1);assert.ok(!events.some(e=>e[0]==='sent'))}
 else {assert.equal(storage.size,0);assert.equal(state.shown.value,false);assert.ok(events.some(e=>e[0]==='sent'&&e[1].status===status))}
})
