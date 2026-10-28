import { ref } from 'vue'
export const realtimeStatus = ref('Connecting')
let socket, starting
const rooms = new Map()
const listeners = new Set()
const viewers = new Map()
function emitRoom(key, subscribe) {
  const [doctype,name] = JSON.parse(key)
  socket?.emit(name ? (subscribe?'doc_subscribe':'doc_unsubscribe') : (subscribe?'doctype_subscribe':'doctype_unsubscribe'),doctype,...(name?[name]:[]))
}
// A browser on the web port reaches Socket.IO on its own port. Behind a proxy or tunnel on the default port,
// the proxy forwards /socket.io on the same origin.
export function socketOrigin(location,socketPort) {
  const url=new URL(location.origin)
  if(socketPort&&location.port)url.port=socketPort
  return url.origin
}
// Socket.IO loads in its own chunk, so it does not delay the first paint. Rooms and viewers wait in the maps until it connects.
export function startRealtime() {
  if(starting) return starting
  const root=document.getElementById('app')
  if(!root?.dataset.site) {realtimeStatus.value='Updates unavailable';return Promise.resolve(null)}
  starting=import('socket.io-client').then(({io})=>connect(io,root))
  return starting
}
function connect(io,root) {
  socket=io(socketOrigin(location,root.dataset.socketPort)+'/'+root.dataset.site,{withCredentials:true,transports:['websocket'],reconnection:true,reconnectionDelay:1000,reconnectionDelayMax:10000})
  socket.on('connect',()=>{realtimeStatus.value='Live';for(const key of rooms.keys())emitRoom(key,true);for(const key of viewers.keys())socket.emit('doc_open',...JSON.parse(key));for(const fn of listeners)fn({kind:'reconnect'})})
  socket.on('disconnect',()=>{realtimeStatus.value='Reconnecting';for(const callbacks of viewers.values())for(const fn of callbacks)fn([])})
  socket.on('connect_error',()=>{realtimeStatus.value='Reconnecting'})
  socket.on('doc_viewers',event=>{for(const fn of viewers.get(JSON.stringify([event.doctype,event.docname]))||[])fn(event.users||[])})
  socket.on('list_update', event => {
    const kind = { Contact: 'contacts', 'Relay Contact Endpoint': 'contacts', 'Relay Team': 'teams', 'Relay Conversation Assignment': 'inbox', 'Relay Canned Reply': 'canned_replies' }[event?.doctype]
    if (kind) for (const fn of listeners) fn({ kind })
  })
  socket.on('update_user_permissions',()=>{for(const fn of listeners)fn({kind:'permissions'})})
  socket.on('relay_changed',event=>{for(const fn of listeners)fn(event)})
  socket.on('relay_ticket_notice',event=>{for(const fn of listeners)fn({...event,kind:'ticket_notice'})})
  socket.on('relay_campaign_progress',event=>{for(const fn of listeners)fn({...event,kind:'campaign_progress'})})
  return socket
}
export function subscribeRoom(doctype,name) {
  const key=JSON.stringify([doctype,name||''])
  startRealtime();rooms.set(key,(rooms.get(key)||0)+1)
  if(rooms.get(key)===1&&socket?.connected)emitRoom(key,true)
  return ()=>{const count=(rooms.get(key)||1)-1;if(count)rooms.set(key,count);else{rooms.delete(key);emitRoom(key,false)}}
}
export function onRealtime(fn) {listeners.add(fn);return ()=>listeners.delete(fn)}
// Successful local read mutations also invalidate queues while a socket reconnects.
export function invalidateReads() {for (const fn of listeners) fn({kind:'reads'})}

// Frappe verifies document access before joining its live viewer room.
export function watchDocumentViewers(doctype,name,fn) {
  const key=JSON.stringify([doctype,name]);startRealtime()
  if(!viewers.has(key))viewers.set(key,new Set())
  viewers.get(key).add(fn)
  if(viewers.get(key).size===1 && socket?.connected)socket.emit('doc_open',doctype,name)
  return ()=>{const callbacks=viewers.get(key);callbacks?.delete(fn);if(!callbacks?.size){viewers.delete(key);socket?.emit('doc_close',doctype,name)}}
}
