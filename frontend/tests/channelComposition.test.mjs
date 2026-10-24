import test from 'node:test'
import assert from 'node:assert/strict'
import { addressList, channelStatus, compositionScope, emailComposition, telegramLimit } from '../src/services/channelComposition.js'
const message = {name:'message',channel:'email',sender_endpoint:'sender@example.invalid',business_doctype:'Customer',business_name:'customer',provider_context:{provider:'Email',email_thread_id:'thread',mailbox_addresses:['inbox@example.invalid']},message_data:{email:{subject:'Order 25',to:['inbox@example.invalid'],cc:['copy@example.invalid']}}}
test('draft scope separates users, businesses, topics and threads',()=>{
  for(const changed of [{...message,name:'other'}, {...message,business_name:'supplier'}, {...message,channel:'telegram'}, {...message,provider_context:{email_thread_id:'other'} }]) assert.notEqual(compositionScope(message,'alice'),compositionScope(changed,'alice'))
  assert.notEqual(compositionScope(message,'alice'),compositionScope(message,'bob'))
})
test('reply-all excludes the mailbox; forward clears addressing and BCC',()=>{
  assert.equal(emailComposition(message,'reply-all').cc,'copy@example.invalid')
  assert.equal(emailComposition(message,'forward').to,'')
  assert.equal(emailComposition(message,'forward').bcc,'')
  assert.equal(emailComposition(message).subject,'Re: Order 25')
  assert.deepEqual(addressList('A@example.invalid, a@example.invalid; b@example.invalid'),['a@example.invalid','b@example.invalid'])
  assert.throws(()=>addressList('A <a@example.invalid>'))
})
test('reply-all excludes configured aliases and deduplicates recipients case-insensitively',()=>{
  const context = {...message.provider_context,mailbox_addresses:['INBOX@example.invalid',' Alias@Example.Invalid '],
    to:['Inbox@Example.Invalid','ALIAS@example.invalid','SENDER@example.invalid','Copy@Example.Invalid'],
    cc:['alias@example.invalid','copy@example.invalid',' other@example.invalid ']}
  const result = emailComposition({...message,sender_endpoint:'Sender@Example.Invalid',provider_context:JSON.stringify(context)},'reply-all')
  assert.equal(result.to,'sender@example.invalid')
  assert.equal(result.cc,'copy@example.invalid, other@example.invalid')
  assert.equal(emailComposition({...message,provider_context:{provider:'Email'}},'reply-all').cc,'inbox@example.invalid, copy@example.invalid','Recipient headers alone cannot identify the mailbox')
})
test('provider acceptance is not delivery or customer read evidence',()=>{
  const status=(provider,status)=>channelStatus({status,provider_context:{provider}})
  assert.equal(status('Email','Sent'),'SMTP accepted')
  assert.equal(status('Telegram','Submitted'),'Bot accepted')
  assert.equal(status('Telegram','Unconfirmed'),'Uncertain')
  assert.equal(status('Email','Failed'),'Bounced')
  assert.equal(channelStatus({status:'Failed',_pending:true,provider_context:{provider:'Email'}}),'Rejected')
  assert.equal(status('Email','Delivered'),'Delivered')
  assert.equal(status('Telegram','Read'),'Read by agent')
  assert.equal(telegramLimit('text'),4096);assert.equal(telegramLimit('photo'),1024)
})


test('stored drafts survive reload without crossing a changed scope',async()=>{
  const {readFile}=await import('node:fs/promises')
  const {ref,watch,effectScope}=await import('vue')
  const {sha256Hex}=await import('../src/services/crypto.js')
  const code=(await readFile(new URL('../src/composables/useStoredDraft.js',import.meta.url),'utf8')).replace(/^import .*\n/gm,'').replace('export function','function')
  const useDraft=new Function('watch','sha256Hex',code+'\nreturn useStoredDraft;')(watch,sha256Hex)
  const saved=new Map();globalThis.sessionStorage={getItem:key=>saved.get(key),setItem:(key,value)=>saved.set(key,value),removeItem:key=>saved.delete(key)}
  const scope=effectScope(),name=ref('customer'),body=ref('')
  scope.run(()=>useDraft(()=>name.value,()=>({body:body.value}),draft=>body.value=draft.body))
  body.value='Quantity 25';scope.stop();body.value=''
  const reload=effectScope();reload.run(()=>useDraft(()=>name.value,()=>({body:body.value}),draft=>body.value=draft.body))
  assert.equal(body.value,'Quantity 25')
  name.value='supplier';assert.equal(body.value,'');body.value='Quantity 50';name.value='customer'
  assert.equal(body.value,'Quantity 25');reload.stop()
})
