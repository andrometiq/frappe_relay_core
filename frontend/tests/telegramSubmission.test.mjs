import test from 'node:test'
import assert from 'node:assert/strict'
import { webcrypto } from 'node:crypto'
import { stableSubmission } from '../src/services/submission.js'
import { telegramSubmission } from '../src/services/telegramSubmission.js'

test('restored group receipt clears the original retry key, preserving unrelated drafts', async()=>{
  const descriptor=Object.getOwnPropertyDescriptor(globalThis,'crypto'), memory=new Map()
  Object.defineProperty(globalThis,'crypto',{configurable:true,value:webcrypto})
  globalThis.sessionStorage={getItem:k=>memory.get(k),setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)}
  try {
    for(const optional of [{},{reply_to:12},{message_thread_id:7},{reply_to:12,message_thread_id:7}]) {
      const original={chat_id:-100100,text:'Hello',...optional}
      let first
      // Existing browser keys created before normalization must still recover.
      await assert.rejects(stableSubmission('relay-telegram',original,async key=>{first=key;throw Error('Receipt lost')}))
      const other={...original,text:'Different draft'}
      await assert.rejects(telegramSubmission(other,async()=>{throw Error('Still pending')}))
      const restored={message_thread_id:0,reply_to:0,...original}
      await telegramSubmission(restored,async key=>assert.equal(key,first))
      assert.equal(memory.size,1,'Only the completed submission is cleared')
      await telegramSubmission(original,async key=>assert.notEqual(key,first,'Intentional identical new message gets a new key'))
      await telegramSubmission(other,async()=>({status:'Submitted'}))
      assert.equal(memory.size,0)
    }
  } finally {
    if(descriptor)Object.defineProperty(globalThis,'crypto',descriptor);else delete globalThis.crypto
    delete globalThis.sessionStorage
  }
})
