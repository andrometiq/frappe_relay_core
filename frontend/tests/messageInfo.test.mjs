import test from 'node:test'
import assert from 'node:assert/strict'
import {ref,nextTick} from 'vue'
import {useMessageInfo} from '../src/composables/useMessageInfo.js'
test('open message info tracks replaced rows and protects coverage from stale responses',async()=>{
 const rows=ref([{name:'one',status:'Sent'}]),contact=ref('first'),requests=[]
 const state=useMessageInfo(()=>rows.value,()=>contact.value,()=>new Promise(resolve=>requests.push(resolve)))
 const first=state.showInfo(rows.value[0]);requests.shift()({read:0});await first
 rows.value=[{name:'one',status:'Delivered'}];await nextTick()
 assert.equal(state.info.value.status,'Delivered')
 const stale=state.refreshCoverage(),fresh=state.refreshCoverage()
 requests[1]({read:2});await fresh;requests[0]({read:1});await stale
 assert.equal(state.coverage.value.read,2)
 requests.length=0
 const pending=state.refreshCoverage();contact.value='second';await nextTick();requests[0]({read:9});await pending
 assert.equal(state.info.value,null);assert.equal(state.coverage.value,null)
})
test('failed authorization refresh clears old read coverage',async()=>{
 let fail=false
 const state=useMessageInfo(()=>[],()=> 'contact',async()=>{if(fail)throw Error('Access denied');return {read:2}})
 await state.showInfo({name:'one'});assert.equal(state.coverage.value.read,2)
 fail=true;await state.refreshCoverage()
 assert.equal(state.coverage.value,null);assert.equal(state.coverageError.value,'Access denied')
})
