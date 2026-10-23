<script setup>
import { ref, watch } from 'vue'
import { Button } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { useRealtimeRefresh } from '../../composables/useRealtimeRefresh'
const props=defineProps({message:{type:String,required:true}})
const rows=ref([]),next=ref(null),page=ref(null),busy=ref(false),error=ref('')
let generation=0
async function load(after=null) {
 const current=++generation
 busy.value=true;error.value=''
 try {
  const result=await coreApi('delivery_receipts.directory',{message:props.message,...(after?{after}:{})})
  if(current!==generation)return
  rows.value=result.items;next.value=result.next;page.value=after
 }catch(e){if(current===generation)error.value=e.message}
 finally{if(current===generation)busy.value=false}
}
function receiptTime(value){const date=new Date(Number(value)*1000);return Number.isNaN(date.getTime())?'Unavailable':date.toLocaleString()}
watch(()=>props.message,()=>{rows.value=[];next.value=null;page.value=null;load()}, {immediate:true})
useRealtimeRefresh(['Relay Message'],['messages'],()=>load(page.value))
</script>
<template>
 <section aria-label="Group participant receipts" class="mt-4 space-y-2">
  <div class="flex items-center justify-between gap-2"><h3 class="font-medium">Participant delivery receipts</h3><Button label="Refresh receipts" :loading="busy" @click="load(page)" /></div>
  <p class="text-xs text-ink-gray-5">Delivery and read status reported by WhatsApp for each participant.</p>
  <p v-if="error" role="alert">{{error}}</p>
  <p v-if="!busy&&!rows.length&&!error" class="text-sm text-ink-gray-5">No participant receipts on this page.</p>
  <div v-if="rows.length" class="overflow-x-auto">
   <table class="w-full text-sm text-left"><thead><tr class="border-b"><th class="p-2">Participant</th><th class="p-2">Status</th><th class="p-2">Time</th></tr></thead>
    <tbody><tr v-for="row in rows" :key="row.name" class="border-b"><td class="p-2 break-all">{{row.participant}}</td><td class="p-2">{{row.status}}</td><td class="p-2">{{receiptTime(row.provider_timestamp)}}</td></tr></tbody>
   </table>
  </div>
  <div class="flex gap-2"><Button v-if="page" label="First participants" :disabled="busy" @click="load()" /><Button v-if="next" label="More participants" :disabled="busy" @click="load(next)" /></div>
 </section>
</template>
