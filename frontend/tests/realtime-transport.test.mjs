import { realpathSync } from 'node:fs'
import { resolve } from 'node:path'
import test from 'node:test'
import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import {setTimeout as wait} from 'node:timers/promises'
import {once} from 'node:events'
import {realtimeRefreshQueue} from '../src/services/realtimeRefreshQueue.js'
// Use the bench's installed Socket.IO server, never a public service.
const require=createRequire(resolve(realpathSync(new URL('../node_modules', import.meta.url)), '../../../frappe/package.json'))
const {Server}=require('socket.io')

test('production client uses WebSocket, rejoins rooms and catches up once after transport loss',async()=>{
 const rt=await import('../src/services/realtime.js')
 const io=new Server({cors:{origin:true}})
 io.listen(0,{host:'127.0.0.1'})
 await once(io.httpServer,'listening')
 const port=io.httpServer.address().port
 globalThis.location={origin:'http://127.0.0.1:8000',port:'8000'}
 globalThis.document={getElementById:()=>({dataset:{site:'relay-test',socketPort:String(port)}})}
 const connections=[],subscriptions=[],batches=[],opened=[],viewers=[]
 io.of('/relay-test').on('connection',s=>{connections.push(s);s.on('doctype_subscribe',dt=>subscriptions.push(dt));s.on('doc_open',(dt,name)=>{opened.push([dt,name]);s.emit('doc_viewers',{doctype:dt,docname:name,users:['fixture-user']})})})
 const queue=realtimeRefreshQueue(async({kinds})=>batches.push([...kinds]),()=>true,10)
 const off=rt.onRealtime(e=>queue.schedule(e.kind)),leave=rt.subscribeRoom('Relay Message')
 const stopViewers=rt.watchDocumentViewers('Relay Contact','fixture-contact',users=>viewers.push(users))
 const client=await rt.startRealtime()
 try{
  if(!client.connected)await once(client,'connect')
  await wait(80)
  assert.equal(client.io.engine.transport.name,'websocket')
  assert.deepEqual(subscriptions,['Relay Message'])
  assert.deepEqual(viewers,[['fixture-user']])
  assert.deepEqual(batches,[['reconnect']])
  for(let i=0;i<100;i++)connections[0].emit('relay_changed',{kind:'messages'})
  await wait(100);assert.deepEqual(batches[1],['messages'])
  connections[0].emit('list_update', {doctype:'Contact'})
  await wait(80);assert.deepEqual(batches.at(-1), ['contacts'])
  connections[0].emit('relay_changed', {kind:'reads'})
  await wait(80);assert.deepEqual(batches.at(-1), ['reads'])
  connections[0].emit('relay_campaign_progress', {name:'Winter launch Oct 2026', counts:{sent:5}})
  await wait(80);assert.deepEqual(batches.at(-1), ['campaign_progress'])
  const initial=batches.length;await wait(200);assert.equal(batches.length,initial)
  const connected=once(client,'connect');connections[0].conn.close();await connected;await wait(100)
  assert.equal(connections.length,2)
  assert.equal(opened.length,2)
  assert.deepEqual(viewers,[['fixture-user'],[],['fixture-user']])
  assert.deepEqual(subscriptions,['Relay Message','Relay Message'])
  assert.deepEqual(batches.slice(initial),[['reconnect']])
 }finally{stopViewers();leave();off();queue.dispose();client.disconnect();await io.close();delete globalThis.document;delete globalThis.location}
})

test('the socket uses its own port only when the browser reaches the web port directly', async () => {
 const {socketOrigin}=await import('../src/services/realtime.js')
 assert.equal(socketOrigin({origin:'http://relay.localhost:8001',port:'8001'},'9001'),'http://relay.localhost:9001')
 assert.equal(socketOrigin({origin:'https://relay.trycloudflare.com',port:''},'9001'),'https://relay.trycloudflare.com')
 assert.equal(socketOrigin({origin:'https://relay.example.com',port:''},''),'https://relay.example.com')
})
