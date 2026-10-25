import { resetRecipient } from '../src/services/recipientContext.js'
import test from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {computed,ref,watch,reactive,nextTick,effectScope} from 'vue'
import {messageData,objectValue} from '../src/components/messageContent.js'
import {sha256Hex} from '../src/services/crypto.js'

const source=(await readFile(new URL('../src/composables/useMessages.js',import.meta.url),'utf8'))
  .replace(/^import[\s\S]*?from ["'][^"']+["'];?\n/gm,'').replace('export function','function')
const factory=new Function('useRealtimeRefresh','sha256Hex','randomUUID','computed','onMounted','onBeforeUnmount','ref','watch','reactive','coordinates','coreApi','messageData','objectValue','resetRecipient','"use strict";\n'+source+'\nreturn useMessages();')
function storage(){
  const value={}
  Object.defineProperties(value,{
    getItem:{value:key=>value[key]??null},setItem:{value:(key,item)=>value[key]=String(item)},removeItem:{value:key=>delete value[key]},
  })
  return value
}
function setup(api){
  globalThis.document={visibilityState:'visible'}
  globalThis.sessionStorage=storage()
  let refresh,id=0
  const scope=effectScope()
  const state=scope.run(()=>factory((dt,kinds,fn)=>refresh=fn,sha256Hex,()=>`key-${++id}`,computed,()=>{},()=>{},ref,watch,reactive,()=>{},api,messageData,objectValue,resetRecipient))
  return {state,refresh:(...kinds)=>refresh({kinds:new Set(kinds)}),stop:()=>scope.stop()}
}
const row=(number,time)=>({name:`RELAY-MSG-${String(number).padStart(10,'0')}`,channel:'channel',content:'Hello',creation:'2026-10-24',sent_at:time,provider_context:{provider:'WhatsApp'},sender_endpoint:'15550000001'})

test('manager triage starts, loads pending messages and watches the selected contact',async()=>{
  const text=await readFile(new URL('../src/components/IncomingWorkspace.vue',import.meta.url),'utf8')
  const script=text.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*\n/gm,'')
  const make=new Function('useRealtimeRefresh','onMounted','ref','watch','coreApi','useEnabledChannels',
    '"use strict";\n'+script+'\nreturn {rows,contact,business,businesses,error};')
  const pending={event:'event',contact:'contact',ambiguous:true,medium:'WhatsApp'},businesses=[{doctype:'Customer',name:'customer'}]
  let mount
  const api=async(method,args)=>{
    if(method==='enrollment.pending')return {items:[pending],next:null}
    assert.equal(method,'enrollment.businesses')
    assert.equal(args.contact,'contact')
    return businesses
  }
  const scope=effectScope()
  try{
    const state=scope.run(()=>make(()=>{},fn=>mount=fn,ref,watch,api,()=>()=>true))
    await mount()
    assert.deepEqual(state.rows.value,[pending])
    state.business.value='previous'
    state.contact.value='contact'
    await nextTick()
    assert.equal(state.business.value,'')
    assert.deepEqual(state.businesses.value,businesses)
    assert.equal(state.error.value,'')
    state.contact.value=''
    await nextTick()
    assert.deepEqual(state.businesses.value,[])
  }finally{scope.stop()}
})

test('catch-up across 150 rows preserves pagination and advances the ingestion cursor',async()=>{
  const messages=Array.from({length:202},(_,index)=>row(index+1,'2026-10-24'))
  const cursors=[]
  const api=async(method,args)=>{
    if(method==='api.message_snapshots')return {items:messages.filter(row=>JSON.parse(args.names).includes(row.name))}
    assert.equal(method,'api.messages')
    if(!args.since)return {items:[messages[0]],first:messages[0].name,last:messages[0].name,ingestion_cursor:messages[0].name,has_more:false}
    cursors.push(args.since)
    const offset=messages.findIndex(row=>row.name===args.since)+1
    const items=messages.slice(offset,offset+args.limit)
    return {items,ingestion_cursor:items.at(-1)?.name||args.since,has_more:offset+items.length<messages.length}
  }
  const fixture=setup(api)
  try{
    fixture.state.selected.value='contact'
    await fixture.state.history()
    await fixture.refresh('messages')
    assert.equal(fixture.state.connectionError.value,'')
    assert.equal(fixture.state.more.value,true)
    assert.deepEqual(fixture.state.rows.value.map(row=>row.name),messages.slice(-150).map(row=>row.name))
    assert.deepEqual(cursors,[0,50,100,150,200].map(index=>messages[index].name))
    await fixture.refresh('messages')
    assert.equal(cursors.length,6)
    assert.equal(cursors.at(-1),messages.at(-1).name)
    assert.equal(fixture.state.connectionError.value,'')
    assert.equal(fixture.state.rows.value.length,150)
  }finally{fixture.stop()}
})

test('realtime discovers late provider timestamps and drains ingestion pages',async()=>{
  const first=row(1,'2026-10-24'),late=row(2,'2020-01-01'),last=row(3,'2026-10-25'),calls=[]
  const api=async(method,args)=>{
    calls.push({method,args})
    if(method==='api.message_snapshots')return {items:[first]}
    assert.equal(method,'api.messages')
    if(!args.since)return {items:[first],first:first.name,last:first.name,ingestion_cursor:first.name}
    assert.equal(args.after,undefined)
    if(args.since===first.name)return {items:[late],ingestion_cursor:late.name,has_more:true}
    return {items:[last],ingestion_cursor:last.name,has_more:false}
  }
  const fixture=setup(api)
  try{
    fixture.state.selected.value='contact'
    await fixture.state.history()
    await fixture.refresh('messages')
    assert.deepEqual(fixture.state.rows.value.map(row=>row.name),[late.name,first.name,last.name])
    await fixture.refresh('messages')
    assert.equal(calls.filter(row=>row.method==='api.messages').at(-1).args.since,last.name)
  }finally{fixture.stop()}
})

test('completed queued action retires its key; identical composition gets a fresh key',async()=>{
  const first=row(1,'2026-10-24'),keys=[]
  const api=async(method,args)=>{
    if(method==='messaging.send'){keys.push(args.request_key);return {action:'RELAY-MA-0000000001',status:'Queued'}}
    if(method==='messaging.action_snapshots')return {items:[{action:'RELAY-MA-0000000001',status:'Submitted',message:'outgoing'}]}
    if(method==='messaging.pending_messages'||method==='api.conversation_channels')return {items:[]}
    if(method==='api.message_snapshots')return {items:[first]}
    if(method==='api.messages')return {items:args.since?[]:[first],first:first.name,last:first.name,ingestion_cursor:first.name}
    throw Error(method)
  }
  const fixture=setup(api)
  try{
    fixture.state.selected.value='contact'
    await fixture.state.send(first,'text',{text:'Same message'})
    assert.equal(fixture.state.error.value,'')
    assert.equal(Object.keys(sessionStorage).length,2)
    await fixture.refresh('message_actions')
    assert.equal(Object.keys(sessionStorage).length,0)
    await fixture.state.send(first,'text',{text:'Same message'})
    assert.deepEqual(keys,['key-1','key-2'])
  }finally{fixture.stop()}
})

test('template lifecycle events refresh after an in-flight request without polling',async()=>{
  const text=(await readFile(new URL('../src/composables/whatsapp/useWhatsAppTemplatesWorkspace.js',import.meta.url),'utf8'))
    .replace(/^import .*\n/gm,'').replace('export function','function')
  let handler,release,lists=0
  const api=async(method,args)=>{
    if(method==='whatsapp.connection')return {configured:true}
    if(args.operation==='capabilities')return {templates:true}
    lists++
    if(lists===1)await new Promise(resolve=>release=resolve)
    return {data:[{id:'1',status:lists===1?'PENDING':'APPROVED'}]}
  }
  const make=new Function('computed','onMounted','ref','coreApi','templateParameterDescriptors','useRealtimeRefresh',text+'\nreturn useWhatsAppTemplatesWorkspace();')
  const state=make(computed,()=>{},ref,api,()=>[],(dt,kinds,fn)=>{
    assert.deepEqual(dt,['Relay WhatsApp Template']);assert.deepEqual(kinds,['templates']);handler=fn
  })
  const initial=state.refresh()
  while(!release)await nextTick()
  await handler();release();await initial
  assert.equal(lists,2)
  assert.equal(state.templates.value[0].status,'APPROVED')
  await new Promise(resolve=>setTimeout(resolve,20))
  assert.equal(lists,2)
})

test('active navigation omits bulk, calls and groups and includes manager triage',async()=>{
  const text=await readFile(new URL('../src/SiteApp.vue',import.meta.url),'utf8')
  assert.match(text, /Contacts: defineAsyncComponent/)
  const contacts = await readFile(new URL('../src/components/ContactsWorkspace.vue', import.meta.url), 'utf8')
  assert.match(contacts, /IncomingWorkspace v-if="tab === 'unlinked' && capabilities.manage"/)
  assert.match(text, /location.hash = '\/contacts\?tab=unlinked'/)
  assert.doesNotMatch(text,/Campaigns:|name:'Campaigns'|name:'Calls'|name:'Groups'/)
})


test('changing to a contact without history clears recipient, quote, draft and attachment', () => {
  const fixture = setup(async () => ({ items: [] }))
  try {
    fixture.state.source.value = row(1, '2026-10-24')
    fixture.state.quoting.value = true
    fixture.state.body.value = 'Private draft for the first contact'
    fixture.state.attachment.value = { filename: 'first-contact.pdf' }
    fixture.state.kind.value = 'document'
    fixture.state.selectRecipient(null)
    assert.equal(fixture.state.source.value, null)
    assert.equal(fixture.state.quoting.value, false)
    assert.equal(fixture.state.body.value, '')
    assert.equal(fixture.state.attachment.value, null)
    assert.equal(fixture.state.kind.value, 'text')
    fixture.state.selectRecipient(row(2, '2026-10-24'))
    assert.equal(fixture.state.source.value.name, row(2, '2026-10-24').name)
    assert.equal(fixture.state.body.value, '')
  } finally { fixture.stop() }
})

test('opening a queue contact clears the previous business context before history loads', async () => {
  const fixture = setup(async method => method.endsWith('view_state') ? {} : { items: [] })
  try {
    fixture.state.businessType.value = 'Customer'
    fixture.state.businessName.value = 'Previous customer'
    fixture.state.businessContext.value = { title: 'Previous customer', contact_count: 5 }
    fixture.state.source.value = row(1, '2026-10-24')
    fixture.state.body.value = 'Previous draft'
    fixture.state.quoting.value = true
    const opened = fixture.state.open('new-contact')
    assert.equal(fixture.state.businessContext.value, null)
    assert.equal(fixture.state.businessName.value, '')
    assert.equal(fixture.state.businessType.value, '')
    assert.equal(fixture.state.source.value, null)
    assert.equal(fixture.state.body.value, '')
    assert.equal(fixture.state.quoting.value, false)
    await opened
    assert.equal(fixture.state.selected.value, 'new-contact')
    assert.equal(fixture.state.error.value, '')
  } finally { fixture.stop() }
})

test('reconnect rechecks every loaded message across channels and removes revoked history',async()=>{
  const messages=Array.from({length:120},(_,index)=>({...row(index+1,'2026-10-24'),provider_context:{provider:index%2?'Email':'Telegram'}}))
  let snapshots=0,reads=0
  const api=async(method,args)=>{
    if(method==='api.messages'){reads++;return {items:args.since?[]:[messages[0]],first:messages[0].name,last:messages[0].name,ingestion_cursor:messages.at(-1).name}}
    if(method==='api.message_snapshots'){snapshots++;return {items:JSON.parse(args.names).filter(name=>name===messages[0].name).map(()=>messages[0])}}
    return {items:[]}
  }
  const fixture=setup(api)
  try {
    fixture.state.selected.value='contact';fixture.state.rows.value=messages
    // Establish the current ingestion cursor with a first history read.
    await fixture.state.history()
    fixture.state.rows.value=messages
    await fixture.refresh('reconnect')
    assert.equal(fixture.state.rows.value.length,1)
    assert.equal(snapshots,3)
    const before=reads;await new Promise(resolve=>setTimeout(resolve,20));assert.equal(reads,before)
  } finally {fixture.stop()}
})

test('permission invalidation clears recipient, pending actions and cached history on denial',async()=>{
  const fixture=setup(async method=>{if(method==='api.messages')throw Object.assign(Error('Revoked'),{status:403});return {items:[]}})
  try {
    fixture.state.selected.value='contact';fixture.state.rows.value=[row(1,'2026-10-24')]
    fixture.state.source.value=row(1,'2026-10-24');fixture.state.body.value='Private draft'
    await fixture.refresh('permissions')
    assert.deepEqual(fixture.state.rows.value,[]);assert.equal(fixture.state.source.value,null);assert.equal(fixture.state.body.value,'')
  } finally {fixture.stop()}
})

test('business reconnect restores only its scoped durable pending attempts',async()=>{
  const pending={name:'pending:action',action:'action',scope:'Customer:local',channel:'email',status:'Queued',_pending:true}
  const fixture=setup(async(method,args)=>{
    if(method==='messaging.pending_messages') {assert.deepEqual(args,{business_doctype:'Customer',business_name:'local'});return {items:[pending]}}
    if(method==='messaging.action_snapshots')return {items:[{action:'action',status:'Queued'}]}
    if(method==='business_inbox.messages')return {items:[]}
    return {items:[]}
  })
  try {
    fixture.state.businessType.value='Customer';fixture.state.businessName.value='local'
    await fixture.refresh('reconnect')
    assert.equal(fixture.state.displayRows.value[0].action,'action')
  } finally {fixture.stop()}
})
