import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash, webcrypto } from 'node:crypto'
import { sha256Hex, randomUUID } from '../src/services/crypto.js'
import { stableSubmission } from '../src/services/submission.js'

test('HTTP browser without subtle/randomUUID preserves hashes and retry keys',async()=>{
 const original=Object.getOwnPropertyDescriptor(globalThis,'crypto')
 const memory=new Map()
 Object.defineProperty(globalThis,'crypto',{configurable:true,value:{getRandomValues:webcrypto.getRandomValues.bind(webcrypto)}})
 globalThis.sessionStorage={getItem:k=>memory.get(k),setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)}
 try {
  for(const text of ['', 'abc','Telegram reply 👋','x'.repeat(100000)])assert.equal(sha256Hex(text),createHash('sha256').update(text).digest('hex'))
  assert.match(randomUUID(),/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  let first
  await assert.rejects(stableSubmission('test',{text:'hello'},async key=>{first=key;throw Error('timeout')}))
  await stableSubmission('test',{text:'hello'},async key=>assert.equal(key,first))
  await stableSubmission('test',{text:'hello'},async key=>assert.notEqual(key,first))
  assert.equal(memory.size,0)
 }finally{if(original)Object.defineProperty(globalThis,'crypto',original);else delete globalThis.crypto;delete globalThis.sessionStorage}
})
