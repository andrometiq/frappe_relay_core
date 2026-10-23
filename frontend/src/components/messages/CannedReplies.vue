<script setup>
import { ref, watch, onBeforeUnmount } from 'vue';
import { Dialog, FormControl, ErrorMessage, Button } from '@relay/ui';
import { sha256Hex, randomUUID } from '../../services/crypto';
import { coreApi } from '../../services/coreApi';
const props=defineProps({source:Object});
const emit=defineEmits(['select','close']);
const open=ref(true), query=ref(''), items=ref([]), error=ref(''), busy=ref(false);
const next=ref(null),cursor=ref(null),history=ref([]);
const running=ref(null),completed=ref({});
async function runAction(item){
 if(running.value)return;
 const source=props.source.name;running.value=item.name;error.value='';
 try{
  const storage='relay-saved-reply-action-'+sha256Hex(JSON.stringify([source,item.name]));
  let key=sessionStorage.getItem(storage);
  if(!key){key=randomUUID();sessionStorage.setItem(storage,key)}
  await coreApi('saved_reply_actions.execute',{message:source,reply:item.name,request_key:key},true);
  if(props.source.name===source)completed.value[item.name]=true;
 }catch(e){if(props.source.name===source)error.value=e.message}
 finally{running.value=null}
}
let timer, generation=0, controller, composing=false;
function reset(){cursor.value=null;history.value=[];next.value=null}
function schedule(){++generation;controller?.abort();clearTimeout(timer);reset();if(!composing)timer=setTimeout(search,300)}
function compositionStart(){composing=true;++generation;controller?.abort();clearTimeout(timer)}
function compositionEnd(){composing=false;schedule()}
function more(){if(busy.value||!next.value)return;history.value.push(cursor.value);cursor.value=next.value;search()}
function back(){if(busy.value||!history.value.length)return;cursor.value=history.value.pop();search()}
async function search() {
  const current=++generation;controller?.abort();controller=new AbortController();busy.value=true;error.value='';
  try {const result=await coreApi('messaging.canned_replies',{message:props.source.name,query:query.value,after:cursor.value},false,{signal:controller.signal});if(current===generation){items.value=result.items;next.value=result.next||null;}}
  catch(e){if(current===generation&&e.name!=='AbortError')error.value=e.message;}
  finally{if(current===generation)busy.value=false;}
}
watch(query,schedule);
watch(()=>props.source.name,()=>{clearTimeout(timer);reset();completed.value={};search()},{immediate:true});
watch(open,value=>{if(!value)emit('close')});
onBeforeUnmount(()=>{++generation;clearTimeout(timer);controller?.abort()});
</script>
<template><Dialog v-model="open" :options="{title:'Saved replies',size:'md'}"><template #body-content>
  <FormControl label="Search saved replies" v-model="query" :maxlength="80" placeholder="Search by title…" @compositionstart="compositionStart" @compositionend="compositionEnd" />
  <ErrorMessage :message="error" /><p v-if="busy" class="p-3 text-sm text-ink-gray-5">Searching…</p>
  <div v-else class="saved-replies"><div v-for="item in items" :key="item.name"><button type="button" @click="emit('select',item);emit('close')">
    <strong>{{item.title}}</strong><small>{{item.language}} · {{item.reply_type || 'Text'}}</small><p>{{item.reply_type==='Location' ? item.latitude+', '+item.longitude : item.reply_type==='Contact' ? item.contact_name+' · '+item.phone : item.body}}</p>
  </button><div v-if="item.action_label" class="px-3 pb-3"><Button :disabled="!!running || completed[item.name]" :loading="running===item.name" @click="runAction(item)">{{completed[item.name] ? 'Action completed' : item.action_label}}</Button><small>Runs for this conversation</small></div></div><p v-if="!items.length" class="p-3 text-sm text-ink-gray-5">No matching saved replies.</p></div>
  <div v-if="history.length || next" class="mt-3 flex justify-between gap-2"><Button :disabled="busy || !history.length" @click="back">Previous replies</Button><Button :disabled="busy || !next" @click="more">More replies</Button></div>
</template></Dialog></template>
