<script setup>
import {ref,onMounted,onBeforeUnmount} from 'vue'
import {Button,FormControl,ErrorMessage} from '@relay/ui'
import BusinessDirectory from './messages/BusinessDirectory.vue'
import RemoteLinkField from './fields/RemoteLinkField.vue'
import RelaySelect from './RelaySelect.vue'
import {coreApi} from '../services/coreApi'
import {useTask} from '../composables/useTask'
import {useRealtimeRefresh} from '../composables/useRealtimeRefresh'
const {busy,error,run}=useTask(),selected=ref(''),businessType=ref(''),job=ref(null),recent=ref([]),businessNames=ref([])
const localDay=date=>new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,10)
const today=new Date(),start=new Date(today);start.setDate(start.getDate()-30)
const fromDate=ref(localDay(start)),toDate=ref(localDay(today)),format=ref('PDF'),includeImages=ref(false),mode=ref('Full messages')
let generation=0
function select(doctype,name){++generation;businessType.value=doctype;selected.value=name;businessNames.value=[name];job.value=null;error.value=''}
async function loadRecent(){try{recent.value=(await coreApi('prepared_reports.recent')).items}catch(e){error.value=e.message}}
function openRecent(row){
 ++generation;businessType.value=row.filters.business_doctype;selected.value=row.filters.business_name;businessNames.value=row.filters.business_names||[row.filters.business_name];
 fromDate.value=row.filters.from_date;toDate.value=row.filters.to_date;format.value=row.filters.output_format;includeImages.value=!!row.filters.include_images;mode.value=row.filters.report_mode||'Full messages';
 job.value=row;refresh()
}
async function refresh(){
 if(!job.value)return
 const name=job.value.name,current=generation
 try{const result=await coreApi('prepared_reports.status',{name});if(current===generation&&job.value?.name===name){job.value=result;await loadRecent()}}
 catch(e){if(current===generation)error.value=e.message}
}
async function prepare(){await run(async()=>{
 const current=++generation
 const result=await coreApi('prepared_reports.request',{filters:JSON.stringify({business_doctype:businessType.value,business_name:selected.value,business_names:businessNames.value,from_date:fromDate.value,to_date:toDate.value,output_format:format.value,report_mode:mode.value,include_images:includeImages.value?1:0})},true)
 if(current!==generation)return
 job.value={name:result.name,status:'Queued',ready:false};await refresh()
})}
function download(){window.open('/api/method/relay_core.prepared_reports.download?'+new URLSearchParams({name:job.value.name}),'_blank','noopener')}
useRealtimeRefresh([],['reports'],refresh)
onMounted(()=>loadRecent())
onBeforeUnmount(()=>{++generation})
</script>
<template>
<section class="page-body space-y-5">
 <h2 class="text-xl font-semibold">Communication reports</h2>
 <p class="text-sm text-ink-gray-6">Choose a business record and date range. Your report is prepared in the background.</p>
 <div class="grid gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
  <aside class="workflow-card"><BusinessDirectory :selected="selected" :busy="busy" @select="select" /></aside>
  <div class="min-w-0 space-y-4"><ErrorMessage :message="error" />
   <section v-if="selected" class="workflow-card space-y-4">
    <h3 class="break-words font-medium">{{businessType}} report</h3>
    <RemoteLinkField multiple v-model="businessNames" :field="{label:'Business records',method:'api.business_records',params:{doctype:businessType},disabled:busy}" />
    <p class="text-xs text-ink-gray-5">Select up to 20 records. Shared messages are included once.</p>
    <div class="grid gap-4 sm:grid-cols-3">
     <FormControl type="date" label="From date" v-model="fromDate" />
     <FormControl type="date" label="To date" v-model="toDate" />
     <RelaySelect label="File format" v-model="format" :options="['PDF','Excel']" />
    </div>
    <RelaySelect label="Report contents" v-model="mode" :options="['Full messages','Daily summary']" />
    <p v-if="mode==='Daily summary'" class="text-xs text-ink-gray-5">AI summaries are grouped by date and channel. Desk summary policies must be enabled for all included channels. Unchanged daily summaries are reused.</p>
    <FormControl v-if="mode==='Full messages'" type="checkbox" label="Include image previews" v-model="includeImages" />
    <p v-if="mode==='Full messages'" class="text-xs text-ink-gray-5">Up to 50 image previews. Other attachments are listed by name and type.</p>
    <p class="text-sm text-ink-gray-5">Messages within the selected dates. For ranges over 20,000 messages, choose a shorter period.</p>
    <Button label="Prepare report" icon-left="file-text" variant="solid" :loading="busy" :disabled="busy || !businessNames.length || businessNames.length>20 || !fromDate || !toDate || fromDate>toDate || ['Queued','Started'].includes(job?.status)" @click="prepare" />
    <div v-if="job" class="rounded-lg border border-outline-gray-2 p-4 space-y-3" role="status" aria-live="polite">
     <p>{{job.status==='Queued'?'Waiting to prepare your report…':job.status==='Started'?'Preparing your report…':job.status==='Completed'&&job.ready?'Your report is ready.':job.status==='Error'?'Report could not be prepared.':'Finishing the report…'}}</p>
     <p v-if="job.filters" class="text-xs text-ink-gray-5">{{(job.filters.business_names||[job.filters.business_name]).join(', ')}} · {{job.filters.from_date}} – {{job.filters.to_date}} · {{job.filters.output_format}} · {{job.filters.report_mode||'Full messages'}}</p>
     <ErrorMessage :message="job.error" />
     <Button v-if="job.ready" label="Download report" icon-left="download" @click="download" />
     <Button v-else label="Check progress" icon-left="refresh-cw" :disabled="busy" @click="refresh" />
    </div>
   </section><p v-else class="text-sm text-ink-gray-5">Select a business record to prepare a report.</p>
   <section v-if="recent.length" class="workflow-card space-y-3">
    <h3 class="font-medium">Recent reports</h3>
    <p class="text-xs text-ink-gray-5">Your 20 most recent reports</p>
    <button v-for="row in recent" :key="row.name" type="button" class="block w-full rounded-lg border border-outline-gray-2 p-3 text-left hover:bg-surface-gray-2" @click="openRecent(row)">
     <strong class="block text-sm">{{row.filters.business_name}}<span v-if="row.filters.business_names?.length>1"> + {{row.filters.business_names.length-1}} more</span></strong>
     <span class="text-xs text-ink-gray-5">{{row.filters.from_date}} – {{row.filters.to_date}} · {{row.filters.output_format}} · {{row.filters.report_mode||'Full messages'}} · {{row.status}}</span>
    </button>
   </section>
  </div>
 </div>
</section>
</template>
