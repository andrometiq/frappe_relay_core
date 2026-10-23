<script setup>
import {ref,watch,onBeforeUnmount} from 'vue';
import {Button} from '@relay/ui';
import {coreApi} from '../services/coreApi';
import {useRealtimeRefresh} from '../composables/useRealtimeRefresh';
const props=defineProps({message:Object});
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
useRealtimeRefresh([],['messages'],()=>{if(open.value)return load()});
</script>
<template><div class="message-transcript">
  <Button :label="open?'Hide transcript':'View transcript'" icon-left="file-text" variant="ghost" :loading="busy" @click="toggle" />
  <section v-if="open" class="rounded border border-outline-gray-2 bg-surface-gray-1 p-3 space-y-2" aria-label="Voice transcript">
    <p v-if="error" role="alert" class="text-ink-red-3">{{error}}</p>
    <template v-else-if="result?.available">
      <p class="whitespace-pre-wrap break-words">{{result.text}}</p>
      <p class="text-xs text-ink-gray-5">Automatically transcribed · Original audio retained</p>
      <details v-if="result.provenance?.model" class="text-xs text-ink-gray-5"><summary>Transcript details</summary>
        <p>{{result.provenance.provider}} · {{result.provenance.model}}</p><p>{{result.provenance.created_at}}</p>
      </details>
    </template>
    <p v-else-if="!busy" class="text-xs text-ink-gray-5">{{result?.status==='pending'?'Transcription is processing…':'No transcript is available for this message.'}}</p>
  </section>
</div></template>
