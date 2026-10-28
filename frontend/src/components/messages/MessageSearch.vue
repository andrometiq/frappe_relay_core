<script setup>
import { useLoadMore } from '../../composables/useLoadMore'
import { ref, watch, onBeforeUnmount } from 'vue'
import { FormControl, ErrorMessage } from '@relay/ui'
import ChatPanel from './ChatPanel.vue'
import { coreApi } from '../../services/coreApi'
const props=defineProps({contact:String})
const emit=defineEmits(['open','close'])
const query=ref(''),rows=ref([]),more=ref(false),busy=ref(false),error=ref(''),searched=ref(false)
let sequence=0,timer,controller
watch(query,()=>{++sequence;controller?.abort();more.value=false;rows.value=[];busy.value=true;clearTimeout(timer);timer=setTimeout(()=>search(),300)})
onBeforeUnmount(()=>{++sequence;clearTimeout(timer);controller?.abort()})
watch(()=>props.contact,()=>{++sequence;rows.value=[];query.value='';more.value=false;busy.value=false;searched.value=false})
async function search(older=false){
 clearTimeout(timer); const ticket=++sequence;controller?.abort();controller=new AbortController()
 if(!query.value.trim()){rows.value=[];more.value=false;searched.value=false;busy.value=false;return}
 busy.value=true;error.value=''
 try{const data=await coreApi('api.messages',{contact:props.contact,query:query.value,limit:30,...(older?{before:rows.value.at(-1)?.name}:{})},false,{signal:controller.signal});if(ticket===sequence){rows.value=[...(older ? rows.value : []),...data.items.slice().reverse()];more.value=data.has_more;searched.value=true}}
 catch(e){if(ticket===sequence&&e.name!=='AbortError')error.value=e.message}finally{if(ticket===sequence)busy.value=false}
}
const moreSentinel = useLoadMore({ loading: busy, hasMore: more, error, load: () => search(true) })
</script>
<template><ChatPanel class="message-search-panel" title="Search conversation" @close="emit('close')"><form @submit.prevent="search()"><FormControl v-model="query" maxlength="200" type="search" aria-label="Search message text" placeholder="Search this conversation"/></form><ErrorMessage :message="error"/><div class="message-search-results"><button v-for="message in rows" :key="message.name" type="button" @click="emit('open',message.name)"><span>{{message.content}}</span><small>{{message.direction==='Outgoing'?'You':'Contact'}} · {{message.creation}}</small></button><p v-if="searched&&!busy&&!rows.length">No matching messages.</p><div v-if="more" ref="moreSentinel" class="h-px" aria-hidden="true" /></div></ChatPanel></template>
<style scoped>
.message-search-panel form{padding:12px 16px}.message-search-results{padding:0 8px 12px}.message-search-results button{display:block;text-align:left;padding:10px 8px;width:100%;border-bottom:1px solid var(--outline-gray-2)}.message-search-results button:hover{background:var(--surface-gray-2)}.message-search-results span{display:block;white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}.message-search-results small{color:var(--ink-gray-5);font-size:12px}.message-search-results p{font-size:13px;padding:12px}
</style>
