import test from 'node:test'
import assert from 'node:assert/strict'
import { setTimeout as wait } from 'node:timers/promises'
import { realtimeRefreshQueue } from '../src/services/realtimeRefreshQueue.js'

for (const delay of [undefined, 40]) test(`bursts respect the ${delay ?? 150} ms delay`, async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const batches=[]
  const q=realtimeRefreshQueue(async ({kinds})=>batches.push([...kinds]),()=>true,delay)
  try {
    for(let i=0;i<30;i++)q.schedule('messages')
    t.mock.timers.tick((delay ?? 150)-1)
    assert.equal(batches.length,0)
    t.mock.timers.tick(1)
    assert.deepEqual(batches,[['messages']])
    await Promise.resolve()
    t.mock.timers.tick(1000)
    assert.equal(batches.length,1)
  } finally { q.dispose() }
})

test('bursts batch, idle never polls, hidden events survive, in-flight events run once more', async () => {
  let visible=true, release
  const batches=[]
  const q=realtimeRefreshQueue(async ({kinds})=>{batches.push([...kinds]);if(batches.length===2)await new Promise(r=>release=r)},()=>visible,5)
  try {
    for(let i=0;i<100;i++)q.schedule('messages')
    q.schedule('message_actions')
    await wait(30)
    assert.deepEqual(batches,[['messages','message_actions']])
    await wait(40);assert.equal(batches.length,1)
    visible=false;q.schedule('messages');await wait(20);assert.equal(batches.length,1)
    visible=true;q.schedule('visible');await wait(20);assert.equal(batches.length,2)
    for(let i=0;i<30;i++)q.schedule('reads')
    await wait(20);assert.equal(batches.length,2)
    release();await wait(25);assert.deepEqual(batches[2],['reads'])
    q.schedule('reconnect');q.dispose();await wait(20);assert.equal(batches.length,3)
  }finally{release?.();q.dispose()}
})

test('failed refresh does not start a retry poll; reconnect retries once', async()=>{
 let count=0
 const q=realtimeRefreshQueue(async()=>{count++;throw Error('offline')},()=>true,5)
 try{q.schedule('messages');await wait(25);await wait(25);assert.equal(count,1);q.schedule('reconnect');await wait(25);assert.equal(count,2)}finally{q.dispose()}
})
