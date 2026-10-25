<script setup>
import {computed,ref,watch,onBeforeUnmount} from 'vue';
import {Button} from '@relay/ui';
import {coreApi} from '../services/coreApi';
import {transcriptState} from './messageContent';
const props=defineProps({message:Object});
const stored=computed(()=>transcriptState(props.message));
// Messages received before inbound transcription keep the on-demand lookup.
const open=ref(false),busy=ref(false),result=ref(null),error=ref('');
let generation=0;
async function load(){
  const current=++generation;busy.value=true;error.value='';
  try{const response=await coreApi('message_derivatives.transcript',{message:props.message.name});if(current===generation)result.value=response;}
  catch(e){if(current===generation)error.value=e.message;}
  finally{if(current===generation)busy.value=false;}
}
function toggle(){open.value=!open.value;if(open.value)load();}
watch(()=>[props.message.name,props.message.edited_at],()=>{++generation;result.value=null;open.value=false;busy.value=false;error.value=''});
onBeforeUnmount(()=>++generation);
</script>
<template><div class="message-transcript">
  <section v-if="stored.state==='available'" class="rounded border border-outline-gray-2 bg-surface-gray-1 p-3 space-y-1" aria-label="Voice transcript">
    <p class="whitespace-pre-wrap break-words">{{stored.text}}</p>
    <p class="text-xs text-ink-gray-5">Automatically transcribed · Original audio retained</p>
  </section>
  <p v-else-if="stored.state!=='legacy'" class="text-xs text-ink-gray-5" role="status" :data-transcript-state="stored.state">{{stored.text}}</p>
  <template v-else>
    <Button :label="open?'Hide transcript':'View transcript'" icon-left="file-text" variant="ghost" :loading="busy" @click="toggle" />
    <section v-if="open" class="rounded border border-outline-gray-2 bg-surface-gray-1 p-3 space-y-2" aria-label="Voice transcript">
      <p v-if="error" role="alert" class="text-ink-red-3">{{error}}</p>
      <p v-else-if="result?.available" class="whitespace-pre-wrap break-words">{{result.text}}</p>
      <p v-else-if="!busy" class="text-xs text-ink-gray-5">{{result?.status==='pending'?'Transcript pending…':'Transcript unavailable.'}}</p>
    </section>
  </template>
</div></template>
