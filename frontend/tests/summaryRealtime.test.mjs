import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {ref,watch,nextTick} from 'vue'
const source=(await readFile(new URL('../src/components/messages/ConversationSummary.vue',import.meta.url),'utf8')).split('<script setup>')[1].split('</script>')[0].replace(/^import .*$/gm,'')
const make=new Function('ref','watch','onBeforeUnmount','defineProps','defineEmits','coreApi','stableSubmission','useRealtimeRefresh','realtimeStatus','setTimeout','clearTimeout',source+'\nreturn {channel,period,summary,refreshSummary};')
test('summary completion uses realtime without disconnected polling and preserves form choices',async()=>{
 const status=ref('Live'),timers=[],requests=[];let refresh,cleanup
 const state=make(ref,watch,fn=>cleanup=fn,()=>({contact:'contact'}),()=>()=>{},async(method)=>{
  requests.push(method)
  if(method==='summaries.options')return [{value:'first'},{value:'second'}]
  if(method==='summaries.latest')return {summary:{name:'summary',status:'Pending'}}
  return {name:'summary',status:'Ready',result:{overview:'Finished summary'}}
 },()=>{},(rooms,kinds,fn)=>refresh=fn,status,(fn,delay)=>{timers.push(delay);return timers.length},()=>{})
 await new Promise(r=>setImmediate(r));await nextTick()
 assert.deepEqual(timers,[])
 state.channel.value='second';state.period.value='7'
 status.value='Reconnecting';await nextTick();assert.deepEqual(timers,[])
 await refresh();assert.equal(state.summary.value.status,'Ready')
 assert.equal(state.channel.value,'second');assert.equal(state.period.value,'7')
 assert.equal(requests.filter(r=>r==='summaries.read').length,1)
 cleanup()
})
