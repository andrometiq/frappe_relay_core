<script setup>
import { recordTitle } from '../../services/recordTitle'
import { computed } from 'vue'
import ChoiceField from './ChoiceField.vue'
import { coreApi } from '../../services/coreApi'
const props=defineProps({field:Object,modelValue:[String,Object,Array],multiple:Boolean})
defineEmits(['update:modelValue'])
const remoteField=computed(()=>({...props.field,search:async(query,signal)=>{
 const rows=await coreApi(props.field.method,{...props.field.params,kind:props.field.kind,query},false,{signal})
 return (Array.isArray(rows)?rows:rows.items||[]).map(row=>({value:row.value||row.name,label:recordTitle(row),description:row.description||''}))
}}))
</script>
<template><ChoiceField :field="remoteField" :multiple="multiple" :model-value="modelValue" @update:model-value="$emit('update:modelValue',$event)"/></template>
