import { ref } from 'vue'
export function useTask() {
 const busy=ref(false),error=ref(''),notice=ref('')
 async function run(work){if(busy.value)return;busy.value=true;error.value='';notice.value='';try{return await work()}catch(e){error.value=e.message}finally{busy.value=false}}
 return {busy,error,notice,run}
}
