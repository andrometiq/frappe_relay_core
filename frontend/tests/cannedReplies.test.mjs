import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {ref,watch,nextTick} from 'vue'
const source=(await readFile(new URL('../src/components/messages/CannedReplies.vue',import.meta.url),'utf8')).split('<script setup>')[1].split('</script>')[0].replace(/^import .*$/gm,'')
const make=new Function('ref','watch','onBeforeUnmount','defineProps','defineEmits','coreApi',source+'\nreturn {query,items,next,history,more,back,compositionStart,compositionEnd};')
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms))
test('saved reply paging replaces results and IME searches only completed text',async()=>{
 const requests=[];let cleanup
 const state=make(ref,watch,fn=>cleanup=fn,()=>({source:{name:'source'}}),()=>()=>{},async(method,args)=>{
  requests.push({...args});return {items:Array.from({length:args.after?5:20},(_,i)=>({name:`${args.after||'first'}-${i}`})),next:args.after?null:'cursor'}
 })
 await nextTick();await wait(0)
 assert.equal(state.items.value.length,20)
 state.more();await wait(0);assert.equal(state.items.value.length,5);assert.equal(state.next.value,null)
 state.back();await wait(0);assert.equal(state.items.value.length,20)
 state.compositionStart();state.query.value='த';await nextTick();await wait(350)
 assert.equal(requests.length,3)
 state.query.value='தமிழ்';state.compositionEnd();await nextTick();await wait(350)
 assert.equal(requests.length,4);assert.equal(requests.at(-1).query,'தமிழ்');assert.equal(requests.at(-1).after,null)
 assert.equal(state.history.value.length,0);cleanup()
})
