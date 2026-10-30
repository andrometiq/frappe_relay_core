import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, nextTick, ref, watch } from 'vue'
import { injectCapabilities } from './channelCapabilities.js'
import { composerKinds, defaultSendSource } from '../src/services/enabledChannels.js'
import { resetRecipient } from '../src/services/recipientContext.js'
import { sha256Hex } from '../src/services/crypto.js'
import { messageData, objectValue } from '../src/components/messageContent.js'
import { coordinates } from '../src/components/formValidation.js'

const source = (await readFile(new URL('../src/composables/useMessages.js', import.meta.url), 'utf8'))
  .replace(/^import .*\n/gm, '').replace('export function', 'function')
const make = new Function('ref', 'computed', 'watch', 'onMounted', 'onBeforeUnmount', 'useRealtimeRefresh', 'coreApi',
  'resetRecipient', 'sha256Hex', 'randomUUID', 'messageData', 'objectValue', 'coordinates', 'inject', 'composerKinds', 'defaultSendSource', source + '\nreturn useMessages();')
const name = index => 'RELAY-MSG-' + String(index).padStart(10, '0')
const row = index => ({ name:name(index), channel:'whatsapp', direction:'Incoming', status:'Sent',
  content:`Local test message ${index}`, creation:name(index), provider_context:{provider:'WhatsApp'} })
const tick = () => new Promise(resolve => setImmediate(resolve))
const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve=yes; reject=no })
  return { promise, resolve, reject }
}

async function fixture(t, count=300, options={}) {
  const previous={}
  for(const key of ['document','window','sessionStorage','location'])previous[key]=globalThis[key]
  globalThis.document={visibilityState:'visible'}
  globalThis.window={history:{pushState(){}},removeEventListener(){}}
  globalThis.location={hash:''}
  globalThis.sessionStorage={getItem(){},setItem(){},removeItem(){}}
  const calls=[], snapshots=[], unmount=[], scope=effectScope()
  const records=new Map([['A',Array.from({length:count},(_,i)=>row(i+1))],['B',[row(900)]]])
  const controls={holdSnapshots:true, holdPending:null, failSnapshots:false, active:0, maxActive:0, latestPage:options.latestPage}
  let realtime, delay
  const api=async(method, values)=>{
    calls.push({method, values})
    const all=records.get(values.contact || values.name) || []
    if(method==='api.conversation_channels')return {items:[{value:'whatsapp'}]}
    if(method==='business_inbox.context')return {name:values.name}
    if(method.endsWith('view_state'))return {}
    if(method.endsWith('save_view'))return {}
    if(method==='messaging.pending_messages')return controls.holdPending?.promise || {items:[]}
    if(method==='messaging.action_snapshots')return {items:[]}
    if(method==='api.message_context'){
      const [contact,items]=[...records].find(([,items])=>items.some(row=>row.name===values.message))
      return {contact,items:items.map(row=>({...row})),first:items[0].name,last:items.at(-1).name,has_more:false,has_newer:false}
    }
    if(method==='api.message_snapshots' || values.names){
      const names=JSON.parse(values.names)
      const result={items:all.filter(row=>names.includes(row.name)).map(row=>({...row}))}
      if(controls.failSnapshots)throw Error('Snapshot unavailable')
      if(!controls.holdSnapshots)return result
      const pending=deferred()
      snapshots.push({names, result, pending, done:false, contact:values.contact || values.name})
      controls.active++;controls.maxActive=Math.max(controls.maxActive,controls.active)
      try{return await pending.promise}finally{controls.active--}
    }
    if(method==='api.messages' || method==='business_inbox.messages'){
      if(values.before){
        const older=all.filter(row=>row.name<values.before), items=older.slice(-values.limit).map(row=>({...row}))
        return {items, first:items[0]?.name, last:items.at(-1)?.name, has_more:older.length>items.length}
      }
      const latest=controls.latestPage ? all.slice(-controls.latestPage) : all
      const items=values.since ? all.filter(row=>row.name>values.since).slice(0,values.limit) : latest.map(row=>({...row}))
      return {items, first:items[0]?.name, last:items.at(-1)?.name,
        ingestion_cursor:items.at(-1)?.name || values.since || name(0),
        has_more:values.since ? all.some(row=>row.name>(items.at(-1)?.name || values.since)) : latest.length<all.length}
    }
    throw Error('Unexpected method: '+method)
  }
  const state=scope.run(()=>make(ref,computed,watch,()=>{},fn=>unmount.push(fn),(_rooms,_kinds,fn,ms)=>{realtime=fn;delay=ms},
    api,resetRecipient,sha256Hex,()=> 'key',messageData,objectValue,coordinates,injectCapabilities,composerKinds,defaultSendSource))
  const releaseWave=async()=>{
    for(const item of snapshots.filter(item=>!item.done)){item.done=true;item.pending.resolve(item.result)}
    await tick()
  }
  const settle=async()=>{
    for(let i=0;i<20 && snapshots.some(item=>!item.done);i++)await releaseWave()
    assert.equal(controls.active,0)
  }
  t.after(async()=>{
    scope.stop();unmount.forEach(fn=>fn())
    controls.holdPending?.resolve({items:[]})
    await settle()
    for(const [key,value] of Object.entries(previous))globalThis[key]=value
  })
  await state.open('A')
  calls.length=0
  return {state,calls,records,controls,snapshots,releaseWave,settle,delay,
    realtime:(kind,messages=[])=>realtime({kinds:new Set([kind]),messages:new Set(messages)})}
}

test('new rows and cursor advance before held snapshots; thread opts into 40 ms', async t=>{
  const f=await fixture(t)
  f.records.get('A').push(row(301))
  await f.realtime('reconnect')
  assert.equal(f.delay,40)
  assert.equal(f.state.rows.value.at(-1).name,name(301))
  assert.equal(f.state.rows.value.length,301)
  assert.equal(f.state.last.value,name(301))
  assert.equal(f.snapshots.length,3)
  assert.equal(f.snapshots.every(item=>!item.done),true)
  await f.realtime('messages')
  assert.equal(f.calls.filter(call=>call.values.since).at(-1).values.since,name(301))
  assert.equal(new Set(f.state.rows.value.map(row=>row.name)).size,301)
})

test('300 rows use six batches with at most three in flight; changed ticks merge and unchanged rows retain identity', async t=>{
  const f=await fixture(t)
  const unchanged=f.state.rows.value[0], changed=f.state.rows.value[10]
  f.records.get('A')[10]={...row(11),status:'Delivered'}
  await f.realtime('reconnect')
  assert.equal(f.controls.active,3)
  await f.releaseWave()
  assert.equal(f.snapshots.length,6)
  assert.equal(f.controls.active,3)
  await f.settle()
  assert.equal(f.controls.maxActive,3)
  assert.deepEqual(f.snapshots.flatMap(item=>item.names),Array.from({length:300},(_,i)=>name(i+1)))
  assert.equal(f.state.rows.value[0],unchanged)
  assert.notEqual(f.state.rows.value[10],changed)
  assert.equal(f.state.rows.value[10].status,'Delivered')
})

test('events during a sweep re-read only the loaded rows they name and preserve arrivals added meanwhile', async t=>{
  const f=await fixture(t)
  await f.realtime('reconnect')
  for(let i=301;i<=305;i++){
    f.records.get('A').push(row(i))
    await f.realtime('messages',[name(i),name(3)])
  }
  assert.equal(f.state.rows.value.at(-1).name,name(305))
  assert.equal(f.snapshots.length,3)
  await f.settle()
  assert.equal(f.snapshots.length,7,'one sweep of six batches, then one read of the changed loaded row')
  assert.deepEqual(f.snapshots.at(-1).names,[name(3)],'new rows from the cursor are not read again')
  assert.equal(f.controls.maxActive,3)
  assert.equal(new Set(f.state.rows.value.map(row=>row.name)).size,305)
  assert.equal(f.state.rows.value.at(-1).name,name(305))
})

for(const business of [false,true])test(`stale ${business?'business':'contact'} sweeps are dropped after conversation changes`,async t=>{
  const f=await fixture(t)
  if(business)await f.state.openBusiness('Customer','A',false)
  await f.realtime('reconnect')
  if(business)await f.state.openBusiness('Supplier','B',false)
  else await f.state.open('B')
  const rows=f.state.rows.value
  await f.settle()
  assert.equal(f.state.rows.value,rows)
  assert.deepEqual(rows.map(row=>row.name),[name(900)])
  assert.equal(f.snapshots.length,3,'stale sweeps do not fetch further waves')
})

for(const latest of [false,true])test(`scrolled-up arrivals accumulate once and appear on ${latest?'Go to latest':'scroll to bottom'}`,async t=>{
  const f=await fixture(t,30)
  const position={name:name(5),offset:42,atBottom:false}
  f.state.rememberPosition(position)
  const original=f.state.rows.value
  f.records.get('A').push(row(31))
  await f.realtime('messages')
  f.records.get('A').push(row(32))
  await f.realtime('messages')
  await f.realtime('messages')
  assert.equal(f.state.rows.value,original)
  assert.equal(f.state.newArrivals.value,2)
  assert.deepEqual(f.state.viewPosition.value,position)
  assert.equal(f.calls.filter(call=>call.values.since).at(-1).values.since,name(32))
  if(latest)await f.state.latest()
  else f.state.rememberPosition({name:name(30),offset:0,atBottom:true})
  assert.equal(f.state.newArrivals.value,0)
  assert.deepEqual(f.state.rows.value.map(row=>row.name),Array.from({length:32},(_,i)=>name(i+1)))
  await f.settle()
  assert.equal(f.state.rows.value.length,32)
})

test('buffered arrivals keep their updated ticks and cannot leak into another conversation',async t=>{
  const f=await fixture(t,30)
  f.state.rememberPosition({name:name(5),offset:42,atBottom:false})
  f.records.get('A').push({...row(31),status:'Read'})
  await f.realtime('messages');await f.settle()
  f.state.rememberPosition({name:name(30),offset:0,atBottom:true})
  assert.equal(f.state.rows.value.at(-1).status,'Read')
  f.state.rememberPosition({name:name(5),offset:42,atBottom:false})
  f.records.get('A').push(row(32))
  await f.realtime('messages')
  await f.state.open('B')
  f.state.rememberPosition({name:name(900),offset:0,atBottom:true})
  assert.deepEqual(f.state.rows.value.map(row=>row.name),[name(900)])
  assert.equal(f.state.newArrivals.value,0)
})

test('busy defers all work and releasing busy refreshes new rows before pending recovery',async t=>{
  const f=await fixture(t,30)
  f.state.busy.value=true;await nextTick()
  f.records.get('A').push(row(31))
  await f.realtime('messages')
  assert.equal(f.calls.length,0)
  f.state.busy.value=false;await nextTick();await tick()
  assert.equal(f.state.rows.value.at(-1).name,name(31))
  assert.equal(f.calls[0].method,'api.messages')
  assert.ok(f.calls.some(call=>call.method==='messaging.pending_messages'))
})

test('sending allows new rows but defers snapshots and pending recovery',async t=>{
  const f=await fixture(t,30)
  f.state.sending.value=1;await nextTick()
  f.records.get('A').push(row(31))
  await f.realtime('visible')
  assert.equal(f.state.rows.value.at(-1).name,name(31))
  assert.deepEqual(f.calls.map(call=>call.method),['api.messages'])
  f.state.sending.value=0;await nextTick();await tick()
  assert.equal(f.snapshots.length,1)
  assert.ok(f.calls.some(call=>call.method==='messaging.pending_messages'))
})

test('visible fetches new rows first and pending recovery cannot block the next message event',async t=>{
  const f=await fixture(t,30)
  f.controls.holdPending=deferred()
  f.records.get('A').push(row(31))
  await f.realtime('visible')
  assert.equal(f.calls[0].method,'api.messages')
  assert.equal(f.state.rows.value.at(-1).name,name(31))
  assert.ok(f.calls.some(call=>call.method==='messaging.pending_messages'))
  f.records.get('A').push(row(32))
  await f.realtime('messages')
  assert.equal(f.state.rows.value.at(-1).name,name(32))
})

test('hidden tabs make no requests',async t=>{
  const f=await fixture(t,30)
  document.visibilityState='hidden'
  await f.realtime('messages');await f.realtime('visible')
  assert.equal(f.calls.length,0)
})

test('snapshot failures leave the new message visible and permit subsequent recovery',async t=>{
  const f=await fixture(t,30)
  f.controls.failSnapshots=true
  f.records.get('A').push(row(31))
  await f.realtime('messages',[name(31),name(5)]);await tick()
  assert.equal(f.state.rows.value.at(-1).name,name(31))
  assert.equal(f.state.connectionError.value,'Snapshot unavailable')
  f.controls.failSnapshots=false;f.controls.holdSnapshots=false
  await f.realtime('messages',[name(5)]);await tick()
  assert.equal(f.state.connectionError.value,'')
  assert.equal(f.state.rows.value.length,31)
})

test('multi-page arrivals appear after each fetch and keep every loaded row once',async t=>{
  const f=await fixture(t)
  f.records.get('A').push(...Array.from({length:120},(_,i)=>row(301+i)))
  await f.realtime('messages')
  assert.deepEqual(f.calls.filter(call=>call.values.since).map(call=>call.values.since),[name(300),name(350),name(400)])
  assert.equal(f.state.rows.value.length,420)
  assert.equal(new Set(f.state.rows.value.map(row=>row.name)).size,420)
  assert.equal(f.state.rows.value[0].name,name(1))
  assert.equal(f.state.last.value,name(420))
})

test('reloading the same conversation invalidates its outstanding sweep',async t=>{
  const f=await fixture(t,30)
  await f.realtime('reconnect')
  f.records.set('A',[{...row(1),status:'Read'}])
  await f.state.history()
  const rows=f.state.rows.value
  await f.settle()
  assert.equal(f.state.rows.value,rows)
  assert.equal(f.state.rows.value[0].status,'Read')
})

test('a failed snapshot waits for its siblings before starting a coalesced sweep',async t=>{
  const f=await fixture(t)
  await f.realtime('reconnect')
  await f.realtime('reconnect')
  f.snapshots[0].done=true;f.snapshots[0].pending.reject(Error('Disconnected'))
  await tick()
  assert.equal(f.snapshots.length,3)
  assert.equal(f.controls.active,2)
  await f.settle()
  assert.equal(f.controls.maxActive,3)
  assert.equal(f.snapshots.length,9)
})

test('arrivals wait while newer history is missing and Go to latest preserves the buffered rows',async t=>{
  const f=await fixture(t,30)
  f.state.newer.value=true
  f.state.rememberPosition({name:name(30),offset:0,atBottom:true})
  f.records.get('A').push(row(31),row(32))
  await f.realtime('messages')
  assert.equal(f.state.rows.value.length,30)
  assert.equal(f.state.newArrivals.value,2)
  // The latest page need not include late provider timestamps; keep those arrivals too.
  f.records.set('A',[row(32)])
  await f.state.latest()
  assert.deepEqual(f.state.rows.value.map(row=>row.name),[name(31),name(32)])
  assert.equal(f.state.newer.value,false)
  assert.equal(f.state.newArrivals.value,0)
})

test('Go to latest releases the actual thread scroll hold after clearing its saved position',async t=>{
  const {reactive}=await import('vue')
  const {createScrollHold}=await import('../src/components/messages/scrollHold.js')
  const component=(await readFile(new URL('../src/components/messages/MessageThread.vue',import.meta.url),'utf8'))
    .match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*\n/gm,'')
  const props=reactive({rows:[],position:{name:'anchor',offset:42,atBottom:false}})
  const scope=effectScope(), unmount=[]
  const bindings={ref,computed,watch,nextTick,onMounted(){},onBeforeUnmount:fn=>unmount.push(fn),
    inject:injectCapabilities,defineProps:()=>props,defineEmits:()=>()=>{},useRealtimeRefresh(){},
    useMessageInfo:()=>({close(){}}),useMobileLayout:()=>false,useLoadMore(){},createScrollHold,
    coreApi:async()=>({readers:[]}),window:{removeEventListener(){}},document:{removeEventListener(){}}}
  const thread=scope.run(()=>new Function(...Object.keys(bindings),component+'\nreturn {viewport,scroll};')(...Object.values(bindings)))
  t.after(()=>{scope.stop();unmount.forEach(fn=>fn())})
  let top=200
  const node={scrollHeight:1000,clientHeight:200,
    get scrollTop(){return top},set scrollTop(value){top=Math.min(800,Math.max(0,value))},
    getBoundingClientRect:()=>({top:0}),querySelectorAll:()=>[
      {dataset:{message:'anchor'},getBoundingClientRect:()=>({top:400-top,bottom:450-top})}]}
  thread.viewport.value=node
  thread.scroll.toMessage('anchor',42)
  assert.equal(thread.scroll.isAtBottom,false)
  props.position={name:'anchor',offset:42,atBottom:false}
  await nextTick();await nextTick()
  assert.equal(thread.scroll.isAtBottom,false,'ordinary position updates keep the anchor')
  props.position=null
  await nextTick();await nextTick()
  assert.equal(thread.scroll.isAtBottom,true)
  assert.equal(node.scrollTop,800)
})

test('older pages only add rows above: loaded rows stay and nothing below loads again',async t=>{
  const f=await fixture(t,500,{latestPage:50})
  assert.equal(f.state.more.value,true)
  for(let page=0;page<9;page++)await f.state.loadOlder()
  const names=f.state.rows.value.map(row=>row.name)
  assert.deepEqual(names,Array.from({length:500},(_,i)=>name(i+1)))
  assert.equal(f.state.newer.value,false,'no newer page is offered after scrolling up')
  assert.equal(f.state.more.value,false)
  assert.equal(f.calls.filter(call=>call.values.after).length,0)
  assert.equal(f.calls.filter(call=>call.values.before).length,9)
})

test('the reconnect sweep checks only the newest loaded rows',async t=>{
  const f=await fixture(t,500,{latestPage:50})
  for(let page=0;page<9;page++)await f.state.loadOlder()
  f.controls.holdSnapshots=false
  await f.realtime('reconnect');await tick()
  const checked=f.calls.filter(call=>call.method==='api.message_snapshots').flatMap(call=>JSON.parse(call.values.names))
  assert.deepEqual(checked,Array.from({length:300},(_,i)=>name(i+201)))
  assert.equal(f.state.rows.value.length,500)
})

test('a live event never reads loaded messages again unless it names them',async t=>{
  const f=await fixture(t,500,{latestPage:50})
  for(let page=0;page<9;page++)await f.state.loadOlder()
  f.controls.holdSnapshots=false
  const loaded=f.state.rows.value.slice()
  f.records.get('A').push(row(501))
  f.records.get('A')[9]={...row(10),status:'Read'}
  await f.realtime('messages',[name(501)]);await tick()
  await f.realtime('messages');await tick()
  assert.equal(f.calls.filter(call=>call.method==='api.message_snapshots').length,0,'new and unnamed events use only the ingestion cursor')
  await f.realtime('messages',[name(10),name(777)]);await tick()
  const checked=f.calls.filter(call=>call.method==='api.message_snapshots').map(call=>JSON.parse(call.values.names))
  assert.deepEqual(checked,[[name(10)]],'only the named loaded message is read')
  assert.equal(f.state.rows.value[9].status,'Read')
  assert.equal(f.state.rows.value[0],loaded[0],'unchanged rows keep their identity, so nothing re-renders')
  assert.equal(new Set(f.state.rows.value.map(row=>row.name)).size,501)
})

test('Go to latest on a fully loaded thread shows the arrivals without loading the thread again',async t=>{
  const f=await fixture(t,30)
  f.state.rememberPosition({name:name(5),offset:42,atBottom:false})
  f.records.get('A').push(row(31))
  await f.realtime('messages')
  assert.equal(f.state.newArrivals.value,1)
  const original=f.state.rows.value.slice()
  f.calls.length=0
  await f.state.latest()
  assert.equal(f.calls.filter(call=>call.method==='api.messages').length,0)
  assert.equal(f.state.viewPosition.value,null)
  assert.deepEqual(f.state.rows.value.slice(0,30),original,'loaded rows keep their identity')
  assert.equal(f.state.rows.value.at(-1).name,name(31))
  assert.equal(f.state.newArrivals.value,0)
})

test('the thread reports its scroll position without focus but marks messages seen only with focus',async t=>{
  const {reactive}=await import('vue')
  const {createScrollHold}=await import('../src/components/messages/scrollHold.js')
  const component=(await readFile(new URL('../src/components/messages/MessageThread.vue',import.meta.url),'utf8'))
    .match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*\n/gm,'')
  const props=reactive({rows:[],position:null}), events=[], scope=effectScope(), unmount=[]
  const page={visibilityState:'visible',focused:false,hasFocus(){return this.focused},removeEventListener(){}}
  const bindings={ref,computed,watch,nextTick,onMounted(){},onBeforeUnmount:fn=>unmount.push(fn),
    inject:injectCapabilities,defineProps:()=>props,defineEmits:()=>(name,value)=>events.push([name,value]),useRealtimeRefresh(){},
    useMessageInfo:()=>({close(){}}),useMobileLayout:()=>false,useLoadMore(){},createScrollHold,
    coreApi:async()=>({readers:[]}),window:{removeEventListener(){}},document:page}
  const thread=scope.run(()=>new Function(...Object.keys(bindings),component+'\nreturn {viewport,trackVisible};')(...Object.values(bindings)))
  t.after(()=>{scope.stop();unmount.forEach(fn=>fn())})
  thread.viewport.value={scrollHeight:2000,scrollTop:200,clientHeight:500,getBoundingClientRect:()=>({top:0,bottom:500}),
    querySelectorAll:()=>[{dataset:{message:'M1'},getBoundingClientRect:()=>({top:40,bottom:200})}]}
  const settle=()=>new Promise(resolve=>setTimeout(resolve,450))
  thread.trackVisible();await settle()
  assert.deepEqual(events.map(([name])=>name),['position'])
  assert.deepEqual(events[0][1],{name:'M1',offset:40,atBottom:false})
  page.focused=true;events.length=0
  thread.trackVisible();await settle()
  assert.deepEqual(events.map(([name])=>name),['position','visible','visibleMessages'])
})

test('Go to latest shows whenever the reader is above the newest message',async()=>{
  const view=await readFile(new URL('../src/components/ConnectedMessages.vue',import.meta.url),'utf8')
  assert.match(view,/class="jump-latest"/)
  assert.match(view.match(/<Button v-if="([^"]+)" class="jump-latest"/)[1],/viewPosition\.value\?\.atBottom === false/)
})

test('a chat opened at a message takes live updates from now, not from its first message',async t=>{
  const f=await fixture(t,30)
  f.records.get('B').unshift(row(800))
  await f.state.focusMessage(name(900))
  assert.equal(f.state.selected.value,'B')
  f.records.get('B').push(row(901))
  await f.realtime('messages')
  assert.deepEqual(f.calls.filter(call=>call.values.since).map(call=>call.values.since),[name(900)])
  assert.deepEqual(f.state.rows.value.map(row=>row.name),[name(800),name(900),name(901)])
})

test('Go to latest stops newer pages before the latest page lands',async t=>{
  const f=await fixture(t,30)
  f.state.newer.value=true
  const going=f.state.latest()
  assert.equal(f.state.newer.value,false)
  await going
  assert.equal(f.state.newer.value,false)
  assert.equal(f.state.rows.value.at(-1).name,name(30))
})

test('Go to latest names one waiting message in the singular',async()=>{
  const view=await readFile(new URL('../src/components/ConnectedMessages.vue',import.meta.url),'utf8')
  const label=view.match(/:label="state\.newArrivals\.value \? (`[^`]*`)/)[1]
  const text=count=>new Function('state','return '+label)({newArrivals:{value:count}})
  assert.equal(text(1),'1 new message')
  assert.equal(text(3),'3 new messages')
})
