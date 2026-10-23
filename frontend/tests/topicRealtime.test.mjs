import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {ref,computed,watch,nextTick,reactive} from 'vue'
const source=(await readFile(new URL('../src/components/messages/ConversationTopics.vue',import.meta.url),'utf8')).split('<script setup>')[1].split('</script>')[0].replace(/^import .*$/gm,'')
const make=new Function('ref','computed','watch','onBeforeUnmount','defineProps','defineEmits','coreApi','randomUUID','useRealtimeRefresh',source+'\nreturn {rows,draft,edit,load,updatesAvailable};')
test('topic refresh preserves draft and rejects old-contact page responses',async()=>{
 const props=reactive({contact:'first',messages:[]}),requests=[];let refresh
 const state=make(ref,computed,watch,()=>{},()=>props,()=>()=>{},(method,args)=>new Promise(resolve=>requests.push({args,resolve})),()=> 'key',(rooms,kinds,fn)=>refresh=fn)
 requests[0].resolve({items:[{name:'old',messages:[]}],next:null});await new Promise(r=>setImmediate(r))
 state.edit();state.draft.value.title='Unfinished topic'
 await refresh();assert.equal(state.draft.value.title,'Unfinished topic');assert.equal(state.updatesAvailable.value,true)
 state.draft.value=null;const old=state.load();props.contact='second';await nextTick()
 requests[2].resolve({items:[{name:'new',messages:[]}],next:null});await new Promise(r=>setImmediate(r))
 requests[1].resolve({items:[{name:'stale',messages:[]}],next:null});await old
 assert.equal(state.rows.value[0].name,'new');assert.equal(state.draft.value,null)
})
