import { ref, computed, watch } from 'vue'
import { coreApi } from '../services/coreApi.js'

export function useMessageInfo(rows, selected, request = coreApi) {
  const info=ref(null),coverage=ref(null),coverageError=ref('')
  let generation=0
  function close(){++generation;info.value=null;coverage.value=null;coverageError.value=''}
  const infoOpen=computed({get:()=>!!info.value,set:value=>{if(!value)close()}})
  async function refreshCoverage(){
    if(!info.value)return
    const current=++generation,name=info.value.name
    coverageError.value=''
    try {
      const result=await request('message_reads.coverage',{message:name})
      if(current===generation)coverage.value=result
    } catch(error){if(current===generation){coverage.value=null;coverageError.value=error.message}}
  }
  function showInfo(message){info.value=message;coverage.value=null;return refreshCoverage()}
  watch(()=>rows().find(row=>row.name===info.value?.name),row=>{if(row)info.value=row})
  watch(selected,close)
  return {info,coverage,coverageError,infoOpen,showInfo,refreshCoverage,close}
}
