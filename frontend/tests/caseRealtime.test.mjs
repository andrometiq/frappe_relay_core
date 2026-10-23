import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {ref,computed,watch,nextTick} from 'vue'
const source=(await readFile(new URL('../src/components/messages/ConversationCases.vue',import.meta.url),'utf8')).split('<script setup>')[1].split('</script>')[0].replace(/^import .*$/gm,'')
const make=new Function('ref','computed','watch','onMounted','defineProps','defineEmits','coreApi','randomUUID','useRealtimeRefresh',source+'\nreturn {open,record,values,updatesAvailable,rows};')
test('case events refresh list but preserve open edits until explicit reload',async()=>{
 let changed;const calls=[]
 const state=make(ref,computed,watch,()=>{},()=>({contact:'contact'}),()=>()=>{},async(method)=>{
  calls.push(method)
  if(method==='cases.directory')return {items:[{name:'case'}],next:null}
  return {name:'case',field_values:{note:'Server text'},definition:{fields:{properties:{}},stages:[]}}
 },()=> 'key',(rooms,kinds,fn)=>changed=fn)
 await changed();assert.equal(state.rows.value.length,1)
 await state.open('case');state.values.value.note='Unfinished edit'
 const before=calls.length;await changed();await nextTick()
 assert.equal(calls.length,before);assert.equal(state.values.value.note,'Unfinished edit');assert.equal(state.updatesAvailable.value,true)
 await state.open('case');assert.equal(state.values.value.note,'Server text');assert.equal(state.updatesAvailable.value,false)
})
