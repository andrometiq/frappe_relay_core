<script setup>
import { useLoadMore } from '../../composables/useLoadMore'
import {ref,watch,onBeforeUnmount} from 'vue'
import {FormControl,ErrorMessage} from '@relay/ui'
import ChatPanel from './ChatPanel.vue'
import {coreApi} from '../../services/coreApi'
const props=defineProps({businessDoctype:String,businessName:String}),emit=defineEmits(['close','open'])
const query=ref(''),rows=ref([]),more=ref(false),busy=ref(false),error=ref('')
let timer,sequence=0
async function search(older=false){
 clearTimeout(timer); const ticket=++sequence;busy.value=true;error.value=''
 try{const page=await coreApi('business_inbox.messages',{doctype:props.businessDoctype,name:props.businessName,query:query.value,limit:30,...(older&&rows.value.length?{before:rows.value.at(-1).name}:{})});if(ticket!==sequence)return;rows.value=[...(older?rows.value:[]),...page.items.slice().reverse()];more.value=page.has_more}
 catch(e){if(ticket===sequence)error.value=e.message}finally{if(ticket===sequence)busy.value=false}
}
watch(query,()=>{clearTimeout(timer);++sequence;rows.value=[];more.value=false;busy.value=false;if(query.value.trim())timer=setTimeout(()=>search(),300)})
onBeforeUnmount(()=>{clearTimeout(timer);++sequence})
const moreSentinel = useLoadMore({ loading: busy, hasMore: more, error, load: () => search(true) })
</script>
<template><ChatPanel title="Search conversation" @close="emit('close')"><div class="p-3 space-y-3"><FormControl v-model="query" label="Find WhatsApp messages" autocomplete="off"/><ErrorMessage :message="error"/><button v-for="row in rows" :key="row.name" type="button" class="block w-full rounded border border-outline-gray-2 p-3 text-left" @click="emit('open',row.name)"><strong class="block text-xs">{{row.contact_label}}</strong><span class="block text-sm line-clamp-2">{{row.content}}</span><small>{{row.creation}}</small></button><p v-if="query.trim()&&!busy&&!rows.length" class="text-sm text-ink-gray-5">No matching WhatsApp messages.</p><div v-if="more" ref="moreSentinel" class="h-px" aria-hidden="true" /></div></ChatPanel></template>
