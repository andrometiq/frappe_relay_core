import {useRealtimeRefresh} from '../useRealtimeRefresh'
import {computed,onMounted,ref} from 'vue'
import {coreApi} from '../../services/coreApi'
import {templateParameterDescriptors} from '../../services/templateParameters'

export function useWhatsAppTemplatesWorkspace(){
 const busy=ref(false),error=ref(''),notice=ref(''),capabilities=ref(null),templates=ref([]),syncStatus=ref(null)
 const editingTemplate=ref(''),template=ref(''),creating=ref(false),name=ref(''),language=ref('en_US'),category=ref('UTILITY'),body=ref(''),parameterValues=ref({})
 const selectedTemplate=computed(()=>templates.value.find(row=>row.id===template.value))
 const parameterKeys=computed(()=>templateParameterDescriptors(selectedTemplate.value))
 const supported=computed(()=>!!capabilities.value?.templates)
 async function execute(operation,arguments_={}){return coreApi('whatsapp.execute',{operation,arguments:arguments_},true)}
 let refreshPending=false
 async function run(fn){if(busy.value)return;busy.value=true;error.value='';notice.value='';try{await fn()}catch(e){error.value=e.message}finally{busy.value=false;if(refreshPending){refreshPending=false;await refresh()}}}
 // The local synced copy shows at once; the server syncs a stale copy from the Hub in the background and a realtime event reloads it.
 async function refresh(){if(busy.value){refreshPending=true;return}await run(async()=>{const hub=execute('capabilities');hub.catch(()=>{});const [connection,local]=await Promise.all([coreApi('whatsapp.connection'),coreApi('whatsapp_templates.directory')]);if(!connection.configured){capabilities.value=null;templates.value=[];return}syncStatus.value=local.sync;templates.value=local.data||[];hub.then(value=>{capabilities.value=value;if(!value.templates)templates.value=[]},e=>{error.value=e.message})})}
 async function deleteTemplate(row){await run(async()=>{await execute('templates.delete',{name:row.name,id:row.id});templates.value=templates.value.filter(item=>item.id!==row.id);notice.value='Template deleted from Meta';template.value=''})}
 useRealtimeRefresh(['Relay WhatsApp Template'],['templates'],refresh)
 onMounted(refresh)
 return {busy,error,notice,capabilities,templates,syncStatus,editingTemplate,template,creating,name,language,category,body,parameterValues,parameterKeys,selectedTemplate,supported,execute,run,refresh,deleteTemplate}
}
