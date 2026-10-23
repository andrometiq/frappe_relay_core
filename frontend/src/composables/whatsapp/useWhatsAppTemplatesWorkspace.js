import {computed,onMounted,ref} from 'vue'
import {coreApi} from '../../services/coreApi'
import {templateParameterDescriptors} from '../../services/templateParameters'

export function useWhatsAppTemplatesWorkspace(){
 const busy=ref(false),loadingMore=ref(false),error=ref(''),notice=ref(''),capabilities=ref(null),templates=ref([]),templateCursor=ref('')
 const editingTemplate=ref(''),template=ref(''),creating=ref(false),name=ref(''),language=ref('en_US'),category=ref('UTILITY'),body=ref(''),parameterValues=ref({})
 const selectedTemplate=computed(()=>templates.value.find(row=>row.id===template.value))
 const parameterKeys=computed(()=>templateParameterDescriptors(selectedTemplate.value))
 const supported=computed(()=>!!capabilities.value?.templates)
 async function execute(operation,arguments_={}){return coreApi('whatsapp.execute',{operation,arguments:arguments_},true)}
 async function run(fn){if(busy.value)return;busy.value=true;error.value='';notice.value='';try{await fn()}catch(e){error.value=e.message}finally{busy.value=false}}
 async function refresh(){await run(async()=>{const connection=await coreApi('whatsapp.connection');if(!connection.configured){capabilities.value=null;templates.value=[];return}capabilities.value=await execute('capabilities');if(!capabilities.value.templates){templates.value=[];return}const page=await execute('templates.list');templates.value=page.data||[];templateCursor.value=page.paging?.cursors?.after||''})}
 async function nextTemplates(){if(!templateCursor.value||loadingMore.value||busy.value)return;loadingMore.value=true;error.value='';try{const page=await execute('templates.list',{after:templateCursor.value});const known=new Set(templates.value.map(row=>row.id));templates.value=[...templates.value,...(page.data||[]).filter(row=>!known.has(row.id))];templateCursor.value=page.paging?.cursors?.after||''}catch(e){error.value=e.message}finally{loadingMore.value=false}}
 async function deleteTemplate(row){await run(async()=>{await execute('templates.delete',{name:row.name,id:row.id});templates.value=templates.value.filter(item=>item.id!==row.id);notice.value='Template deleted from Meta';template.value=''})}
 onMounted(refresh)
 return {busy,loadingMore,error,notice,capabilities,templates,templateCursor,editingTemplate,template,creating,name,language,category,body,parameterValues,parameterKeys,selectedTemplate,supported,execute,run,refresh,nextTemplates,deleteTemplate}
}
