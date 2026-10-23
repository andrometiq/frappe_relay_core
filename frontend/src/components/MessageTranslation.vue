<script setup>
import {ref,watch,onBeforeUnmount} from 'vue';
import {Button} from '@relay/ui';
import {coreApi} from '../services/coreApi';
import {useRealtimeRefresh} from '../composables/useRealtimeRefresh';
const props=defineProps({message:Object}),emit=defineEmits(['visible']);
const open=ref(false),busy=ref(false),result=ref(null),error=ref('');let generation=0;
async function load(){const current=++generation;busy.value=true;error.value='';try{const data=await coreApi('message_derivatives.translation',{message:props.message.name});if(current===generation)result.value=data;}catch(e){if(current===generation)error.value=e.message;}finally{if(current===generation)busy.value=false;}}
function toggle(){open.value=!open.value;if(open.value)load();}
watch([open,result],()=>emit('visible',open.value&&!!result.value?.available));
watch(()=>[props.message.name,props.message.edited_at],()=>{++generation;open.value=false;result.value=null;error.value='';busy.value=false;emit('visible',false)});
onBeforeUnmount(()=>++generation);
useRealtimeRefresh([],['messages'],()=>{if(open.value)return load()});
</script>
<template><div>
<Button :label="open?(result?.available?'View original':'Hide translation'):'View in English'" icon-left="globe" variant="ghost" :loading="busy" @click="toggle" />
<section v-if="open" aria-label="English translation" class="rounded border border-outline-gray-2 bg-surface-gray-1 p-3 space-y-2">
<p v-if="error" role="alert">{{error}}</p>
<template v-else-if="result?.available"><p class="whitespace-pre-wrap break-words">{{result.text}}</p><p class="text-xs text-ink-gray-5">Automatically translated to English · {{result.language}}</p><details class="text-xs text-ink-gray-5"><summary>Translation details</summary><p>{{result.provenance?.provider}} · {{result.provenance?.model}}</p><p>{{result.provenance?.created_at}}</p><p v-for="(segment,index) in result.provenance?.segments || []" :key="index">Part {{index+1}} · {{segment.provider}} · {{segment.model}}</p></details></template>
<p v-else-if="!busy" class="text-xs text-ink-gray-5">{{result?.language==='en'?'This message is already in English.':['pending','processing'].includes(result?.status)?'Translation is processing…':result?.status==='failed'?'Translation could not be completed. The original is available.':'No translation is available for this message.'}}</p>
</section></div></template>
