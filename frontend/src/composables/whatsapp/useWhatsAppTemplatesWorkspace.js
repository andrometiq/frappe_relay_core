import {useRealtimeRefresh} from '../useRealtimeRefresh'
import {computed,onMounted,ref} from 'vue'
import {coreApi} from '../../services/coreApi'
import {templateParameterDescriptors} from '../../services/templateParameters'

export function useWhatsAppTemplatesWorkspace(){
 const busy=ref(false),loadingMore=ref(false),error=ref(''),notice=ref(''),capabilities=ref(null),templates=ref([]),templateCursor=ref(''),syncStatus=ref(null)
 const editingTemplate=ref(''),template=ref(''),creating=ref(false),name=ref(''),language=ref('en_US'),category=ref('UTILITY'),body=ref(''),parameterValues=ref({})
 const selectedTemplate=computed(()=>templates.value.find(row=>row.id===template.value))
 const parameterKeys=computed(()=>templateParameterDescriptors(selectedTemplate.value))
 const supported=computed(()=>!!capabilities.value?.templates)
 async function execute(operation,arguments_={}){return coreApi('whatsapp.execute',{operation,arguments:arguments_},true)}
 let refreshPending=false
 async function run(fn){if(busy.value)return;busy.value=true;error.value='';notice.value='';try{await fn()}catch(e){error.value=e.message}finally{busy.value=false;if(refreshPending){refreshPending=false;await refresh()}}}
 async function refresh(){if(busy.value){refreshPending=true;return}await run(async()=>{const connection=await coreApi('whatsapp.connection');if(!connection.configured){capabilities.value=null;templates.value=[];return}capabilities.value=await execute('capabilities');if(!capabilities.value.templates){templates.value=[];return}const [page,sync]=await Promise.all([execute('templates.list'),coreApi('whatsapp_templates.sync_status')]);syncStatus.value=sync;templates.value=page.data||[];templateCursor.value=page.paging?.cursors?.after||''})}
 async function nextTemplates(){if(!templateCursor.value||loadingMore.value||busy.value)return;loadingMore.value=true;error.value='';try{const page=await execute('templates.list',{after:templateCursor.value});const known=new Set(templates.value.map(row=>row.id));templates.value=[...templates.value,...(page.data||[]).filter(row=>!known.has(row.id))];templateCursor.value=page.paging?.cursors?.after||''}catch(e){error.value=e.message}finally{loadingMore.value=false}}
 async function deleteTemplate(row){await run(async()=>{await execute('templates.delete',{name:row.name,id:row.id});templates.value=templates.value.filter(item=>item.id!==row.id);notice.value='Template deleted from Meta';template.value=''})}
 useRealtimeRefresh(['Relay WhatsApp Template'],['templates'],refresh)
 onMounted(refresh)
 return {busy,loadingMore,error,notice,capabilities,templates,templateCursor,syncStatus,editingTemplate,template,creating,name,language,category,body,parameterValues,parameterKeys,selectedTemplate,supported,execute,run,refresh,nextTemplates,deleteTemplate}
}
