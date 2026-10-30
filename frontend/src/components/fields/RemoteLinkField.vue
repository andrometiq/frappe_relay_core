<script setup>
import { recordTitle } from '../../services/recordTitle'
import { linkedTitle } from '../../services/linkedTitle'
import { computed } from 'vue'
import ChoiceField from './ChoiceField.vue'
import { coreApi } from '../../services/coreApi'
const props=defineProps({field:Object,modelValue:[String,Object,Array],multiple:Boolean})
defineEmits(['update:modelValue'])
const search = computed(() => {
 const {method, params, kind} = props.field
 return async (query, signal) => {
  const rows = await coreApi(method, {...params, kind, query}, false, {signal})
  return (Array.isArray(rows) ? rows : rows.items || []).map(row => ({value:row.value || row.name, label:recordTitle(row), description:recordTitle(row.description, ''), icon:row.icon}))
 }
})
const linkedType = computed(() => props.field.doctype || (props.field.method === 'api.business_records' ? props.field.params?.doctype : {
 'api.contacts': 'Relay Contact', 'inbox.directory': 'Relay Contact', 'api.contact_directory': 'Contact',
 'teams.agents': 'User', 'collaboration.colleagues': 'User', 'cases.agents': 'User',
}[props.field.method]))
const remoteField = computed(() => ({...props.field, search:search.value,
 initialOptions: props.field.initialOptions || (linkedType.value ? (props.multiple ? props.modelValue || [] : [props.modelValue]).filter(Boolean).map(value => ({value, label:linkedTitle(linkedType.value, value)})) : undefined),
}))
</script>
<template><ChoiceField :field="remoteField" :multiple="multiple" :model-value="modelValue" @update:model-value="$emit('update:modelValue',$event)"/></template>
