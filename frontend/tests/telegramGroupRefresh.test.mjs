import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { ref, computed, watch, nextTick } from 'vue';

// Exercise the actual composable with transport and lifecycle boundaries injected.
const source = (await readFile(new URL('../src/composables/useTelegramGroups.js', import.meta.url), 'utf8'))
  .replace(/^import .*;\n/gm, '').replace('export function', 'function');
const subscriptions = [], calls = [];
let older = false;
const coreApi = async (method, args) => {
  calls.push({method,args});
  assert.equal(method, 'telegram_delivery.pending', 'Realtime must read durable state, never reconcile or send');
  older = !!args.before;
  return {items: Array.from({length:older?1:50},(_,i)=>({action:String(i),status:'Queued',args:{text:'Queued'}})), next:older?null:'RELAY-MA-0000000050'};
};
const create = new Function('onMounted','ref','computed','watch','useRealtimeRefresh','telegramSubmission','coreApi','objectValue','positive',source+'\nreturn useTelegramGroups;');
const state = create(()=>{},ref,computed,watch,(types,kinds,fn)=>subscriptions.push({types,kinds,fn}),()=>{throw Error('Unexpected submission')},coreApi,JSON.parse,Number)();
state.selected.value='RELAY-CE-0000000001';
const refresh = subscriptions.find(s=>!s.types.length && s.kinds.includes('message_actions')).fn;
await refresh();
assert.equal(state.pendingSend.value.length,50);
await state.restorePending(true);
assert.equal(state.pendingSend.value.length,51);
await refresh();
assert.equal(state.pendingSend.value.length,51,'Realtime preserves the selected pending page');
assert.equal(calls.at(-1).args.before,'RELAY-MA-0000000050');
await state.restorePending();
assert.equal(state.pendingSend.value.length,50,'Latest replaces rather than appends');
state.busy.value=true;
await nextTick();
const before=calls.length;
await refresh();await refresh();
assert.equal(calls.length,before,'Busy composer defers status refresh');
state.busy.value=false;
await nextTick();await nextTick();
assert.equal(calls.length,before+1,'Deferred events coalesce into one refresh');
assert.equal(state.pendingSend.value.length,50);
console.log('PASS: bounded pending pages, preserved page, no Hub reconciliation/send, coalesced busy refresh');
