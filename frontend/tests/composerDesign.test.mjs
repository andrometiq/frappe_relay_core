import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, nextTick, reactive, ref, watch } from 'vue'
import { overlayKeydown } from '../src/services/overlayFocus.js'
import { composerActions, attachmentKinds } from '../src/services/composerActions.js'
import { channelCan, composerKinds } from '../src/services/enabledChannels.js'
import { sha256Hex } from '../src/services/crypto.js'
import { messageData } from '../src/components/messageContent.js'
import { compositionScope, telegramLimit } from '../src/services/channelComposition.js'
import { useStoredDraft } from '../src/composables/useStoredDraft.js'
import { whatsappCapabilities } from './channelCapabilities.js'
import { attachmentMaxBytes, sizeError, sizeLabel } from '../src/components/messages/attachmentFormats.js'

const setup = async name => (await readFile(new URL(`../src/components/messages/${name}.vue`, import.meta.url), 'utf8'))
  .split('<script setup>')[1].split('</script>')[0].replace(/^import .*\n/gm, '')
const composer = await setup('MessageComposer'), note = await setup('NoteComposer')
function evaluate(source, values, exposed) { return new Function(...Object.keys(values), source + '\nreturn {' + exposed + '};')(...Object.values(values)) }
const settle = async () => { await nextTick(); await nextTick() }
function fixture(t, { provider = 'WhatsApp', window = {open:true,remaining_seconds:7200}, off = '', legacyDraft } = {}) {
  const old = Object.fromEntries(['document', 'sessionStorage'].map(key => [key, globalThis[key]])), storage = new Map(), cleanups = [], scopes = []
  globalThis.document = { getElementById: () => ({dataset:{user:'local-composer-test'}}), visibilityState:'visible' }
  globalThis.sessionStorage = {getItem:key => storage.get(key),setItem:(key,value) => storage.set(key,value),removeItem:key=>storage.delete(key)}
  const source = ref({name:'local-message',channel:'local-channel',relay_contact:'local-contact',sender_endpoint:'local-recipient',provider_context:{provider}})
  const state = Object.fromEntries(Object.entries({selected:'local-contact',businessType:'',businessName:'',rows:[],attachment:null,quoting:false,kind:'text',body:'',latitude:'',longitude:'',contactName:'',phone:'',busy:false,sending:0,error:''}).map(([key,value]) => [key,ref(value)]))
  Object.assign(state, {source,sourceContext:computed(()=>source.value.provider_context),kinds:computed(()=>composerKinds(whatsappCapabilities,source.value.provider_context)),cancelReply:()=>state.quoting.value=false,send:()=>sends.push(state.body.value),uploadAttachment:async()=>{state.attachment.value=null;state.error.value='Upload failed'}})
  if (legacyDraft) storage.set('relay-draft-' + sha256Hex(compositionScope(source.value, 'local-composer-test')), JSON.stringify(legacyDraft))
  const sends = [], events = [], props = reactive({mode:'reply',offText:off})
  let response = window, focused = 0
  const base = { computed, reactive, ref, watch, nextTick, onBeforeUnmount:fn=>cleanups.push(fn), onMounted:()=>{}, useStoredDraft,
    defineProps:()=>props, defineEmits:()=>(...args)=>events.push(args), useMobileLayout:()=>ref(false), useRealtimeRefresh:()=>{},
    coreApi:async method => { if(method==='messaging.reply_window') {if(response instanceof Error) throw response; return response} return {} },
    useWhatsAppIdentity:()=>({identity:ref(null),load:()=>{}}), channelCan, channelOffText:provider=>`${provider} is switched off`,
    compositionScope, telegramLimit, composerActions, attachmentKinds, messageData, sha256Hex, useSendChannel:()=>({choices:ref(new Map())}), sendNumbersKey:'numbers',messagesKey:'messages',
    inject:(key, fallback)=>key==='messages'?state:key==='relayCapabilities'?ref(whatsappCapabilities):fallback,
    setInterval:()=>0, clearInterval:()=>{},setTimeout:()=>0,clearTimeout:()=>{},attachmentFormatError:()=>'',formatBytes:()=>'',attachmentMaxBytes,sizeError,sizeLabel }
  function mount(code, values, exposed) { const scope=effectScope();scopes.push(scope);return scope.run(()=>evaluate(code,{...base,...values},exposed)) }
  const view = mount(composer, {}, 'actions,canSend,closed,windowError,windowHint,checkWindow,keydown,clearQuote,draftInput,moreAction,showCount,editing,characterCount,attachFile,requestedAttachmentKind')
  view.draftInput.value = {style:{},scrollHeight:44,focus:()=>focused++}
  function mountNote() {
    return mount(note, {defineProps:()=>({contact:'local-contact',messages:[],active:false}),businessScope:()=>({}),stableSubmission:async()=>{}}, 'body,mentions,assignedTo,keydown,submit')
  }
  t.after(()=>{cleanups.forEach(fn=>fn());scopes.forEach(scope=>scope.stop());Object.assign(globalThis,old)})
  return {state,view,props,sends,events,mountNote,focusCount:()=>focused,setWindow:value=>response=value}
}

test('more actions follow capabilities, named kinds and stable ordering', () => {
  const can = key => channelCan(whatsappCapabilities,'WhatsApp',key)
  const actions = composerActions({can,kinds:composerKinds(whatsappCapabilities,{provider:'WhatsApp'})})
  assert.deepEqual(actions.map(a=>a.id),['saved','template','photo','video','audio','voice','document','location','contact','sticker','emoji','note','details'])
  assert.equal(actions.find(a=>a.id==='voice').label,'Voice file')
  assert.deepEqual(composerActions({kinds:['text','photo']}).map(a=>a.id),['photo','emoji','note','details'])
  assert.deepEqual(composerActions({can,closed:true}).map(a=>a.id),['template','note','details'])
  assert.deepEqual(composerActions({can,off:true}).map(a=>a.id),['note','details'])
  assert.deepEqual(composerActions({email:true}).map(a=>a.id),['files','note','details'])
  assert.ok(composerActions({can,busy:true}).filter(a=>a.id!=='details').every(a=>a.disabled))
})

test('switching note and reply modes preserves separate drafts, mentions and assignment', async t => {
  const {state,view,props,events,mountNote}=fixture(t);await settle()
  state.body.value='Customer draft with quantity 25'
  view.moreAction('note');assert.deepEqual(events.at(-1),['mode','note']);props.mode='note'
  const first=mountNote();first.body.value='Private follow-up';first.mentions.value=['colleague@example.invalid'];first.assignedTo.value='owner@example.invalid'
  props.mode='reply';await settle();assert.equal(state.body.value,'Customer draft with quantity 25')
  const restored=mountNote();assert.equal(restored.body.value,'Private follow-up');assert.deepEqual(restored.mentions.value,['colleague@example.invalid']);assert.equal(restored.assignedTo.value,'owner@example.invalid')
})

test('closed and failed window checks retain the draft and notes, with different states', async t => {
  const {state,view,setWindow}=fixture(t);await settle();state.body.value='Saved reply'
  assert.equal(view.windowHint.value,'')
  setWindow({open:true,remaining_seconds:1800});await view.checkWindow();assert.match(view.windowHint.value,/30 min/)
  setWindow({open:false});await view.checkWindow();assert.equal(view.closed.value,true);assert.equal(view.canSend.value,false)
  assert.deepEqual(view.actions.value.map(a=>a.id),['template','note','details'])
  setWindow(Error('Offline'));await view.checkWindow();assert.equal(view.closed.value,false);assert.equal(view.windowError.value,'Offline');assert.equal(view.canSend.value,false)
  assert.equal(state.body.value,'Saved reply')
  setWindow({open:true});await view.checkWindow();assert.equal(view.canSend.value,true)
})

test('Enter sends once; Shift+Enter, IME, keyCode 229 and repeat never send', async t => {
  const {state,view,sends}=fixture(t);await settle();state.body.value='Hello'
  for (const extra of [{shiftKey:true},{isComposing:true},{keyCode:229},{repeat:true}]) view.keydown({key:'Enter',preventDefault(){},...extra})
  assert.equal(sends.length,0)
  view.keydown({key:'Enter',preventDefault(){}});assert.deepEqual(sends,['Hello'])
  state.busy.value=true;view.keydown({key:'Enter',preventDefault(){}});assert.equal(sends.length,1)
})

test('cancel quote retains draft and returns focus', async t => {
  const {state,view,focusCount}=fixture(t);await settle();state.body.value='Reply in progress';state.quoting.value=true
  view.clearQuote();await settle();assert.equal(state.quoting.value,false);assert.equal(state.body.value,'Reply in progress');assert.equal(focusCount(),1)
})

test('Telegram counter counts Unicode points, appears near limit while editing and blocks excess', async t => {
  const {state,view}=fixture(t,{provider:'Telegram'});await settle();view.editing.value=true;state.body.value='😀'.repeat(100)
  assert.equal(view.showCount.value,false);state.body.value='😀'.repeat(4096);assert.equal(view.characterCount.value,4096);assert.equal(view.showCount.value,true);assert.equal(view.canSend.value,true)
  state.body.value+='😀';assert.equal(view.canSend.value,false);view.editing.value=false;assert.equal(view.showCount.value,true)
})

test('a failed first upload keeps an attachment composer; failed replacement keeps the previous file', async t => {
  const {state,view}=fixture(t);await settle();state.body.value='Caption';view.requestedAttachmentKind.value='photo'
  await view.attachFile({target:{files:[{name:'photo.png'}],value:'photo.png'}})
  assert.equal(state.kind.value,'photo');assert.equal(view.canSend.value,false);assert.equal(state.body.value,'Caption')
  state.attachment.value={name:'local-attachment',filename:'original.png'}
  await view.attachFile({target:{files:[{name:'replacement.png'}],value:'replacement.png'}})
  assert.equal(state.attachment.value.filename,'original.png')
})


test('a chat attachment may be as large as its WhatsApp kind allows and is refused before upload one byte above', async t => {
  // The fixture upload always fails with 'Upload failed', so that error shows the file reached the upload.
  const {state,view}=fixture(t);await settle()
  const relay=whatsappCapabilities.max_file_bytes, photo=whatsappCapabilities.channels.WhatsApp.max_media_bytes.photo
  for (const [kind,limit] of [['photo',photo],['document',relay]]) {
    view.requestedAttachmentKind.value=kind;state.error.value=''
    await view.attachFile({target:{files:[{name:'file.png',size:limit}],value:''}})
    assert.equal(state.error.value,'Upload failed')
    await view.attachFile({target:{files:[{name:'file.png',size:limit+1}],value:''}})
    assert.equal(state.error.value,`A WhatsApp ${kind} must be at most ${sizeLabel(limit)}.`)
  }
})


test('quoting another message in the same conversation keeps the current draft', async t => {
  const {state}=fixture(t);await settle();state.body.value='Keep this customer reply'
  state.source.value={...state.source.value,name:'older-local-message',sender_endpoint:'historical-own-number',business_doctype:null,business_name:null};await settle()
  assert.equal(state.body.value,'Keep this customer reply')
})


test('an in-flight chat send locks conflicting composer actions without changing the send queue', async t => {
  const {state,view,sends}=fixture(t);await settle();state.body.value='Quantity 25';state.sending.value=1
  assert.equal(view.canSend.value,false);assert.ok(view.actions.value.filter(a=>a.id!=='details').every(a=>a.disabled))
  view.keydown({key:'Enter',preventDefault(){}});assert.equal(sends.length,0)
  state.sending.value=0;assert.equal(view.canSend.value,true)
})


test('the conversation composer restores a draft stored by the previous per-message composer', async t => {
  const {state}=fixture(t,{legacyDraft:{body:'Existing quantity 25 draft',kind:'text'}});await settle()
  assert.equal(state.body.value,'Existing quantity 25 draft')
})

test('overlay keyboard navigation wraps focus, supports arrows and restores on Escape', t => {
  const previous=globalThis.document;globalThis.document={activeElement:null};t.after(()=>globalThis.document=previous)
  const nodes=Array.from({length:3},()=>({getClientRects:()=>[{}],focus(){document.activeElement=this}}))
  const root={querySelectorAll:()=>nodes};let closed=0,prevented=0
  const press=(key,shiftKey=false)=>overlayKeydown({key,shiftKey,target:{matches:()=>false},preventDefault(){prevented++},stopPropagation(){}},root,()=>closed++,{arrows:true})
  nodes[2].focus();press('Tab');assert.equal(document.activeElement,nodes[0])
  press('Tab',true);assert.equal(document.activeElement,nodes[2])
  press('ArrowDown');assert.equal(document.activeElement,nodes[0])
  press('End');assert.equal(document.activeElement,nodes[2])
  press('Home');assert.equal(document.activeElement,nodes[0])
  press('Escape');assert.equal(closed,1);assert.equal(prevented,6)
})


test('changing the conversation recipient restores its own draft without leaking the previous one', async t => {
  const {state}=fixture(t);await settle();state.body.value='Draft for local-contact'
  state.selected.value='other-local-contact';state.source.value={...state.source.value,relay_contact:'other-local-contact'};await settle()
  assert.equal(state.body.value,'');state.body.value='Different recipient draft'
  state.selected.value='local-contact';state.source.value={...state.source.value,relay_contact:'local-contact'};await settle()
  assert.equal(state.body.value,'Draft for local-contact')
})


test('location details do not inherit a Telegram caption limit from the saved text draft', async t => {
  const {state,view}=fixture(t,{provider:'Telegram'});await settle()
  state.body.value='😀'.repeat(4097);view.moreAction('location');state.latitude.value='11.0168';state.longitude.value='76.9558'
  assert.equal(view.canSend.value,true);assert.ok(!view.showCount.value);assert.equal(state.body.value.length,8194)
})
