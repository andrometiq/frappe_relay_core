<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { FormControl, ErrorMessage } from '@relay/ui'
import RelaySelect from './RelaySelect.vue'
import RemoteLinkField from './fields/RemoteLinkField.vue'
import { coreApi } from '../services/coreApi'
const props=defineProps({doctype:String,record:String,disabled:Boolean})
const emit=defineEmits(['update:doctype','update:record'])
const types=ref([]),error=ref('')
watch(()=>props.doctype,()=>emit('update:record',''))
onMounted(async()=>{try{types.value=await coreApi('api.business_types');if(!types.value.includes(props.doctype))emit('update:doctype',types.value[0]||'')}catch(e){error.value=e.message}})
</script>
<template><div class="space-y-3"><RelaySelect label="Business type" :model-value="doctype" :options="types" :disabled="disabled" @update:model-value="emit('update:doctype',$event)"/><RemoteLinkField :key="doctype" :field="{label:'Business record',method:'api.business_records',params:{doctype},readOnly:disabled||!doctype}" :model-value="record" @update:model-value="emit('update:record',$event)"/><ErrorMessage :message="error"/></div></template>
