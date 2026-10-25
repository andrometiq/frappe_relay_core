<script setup>
import { computed, ref, watch } from 'vue'
import ChoiceField from './ChoiceField.vue'
import { coreApi } from '../../services/coreApi'
import { readableName } from '../../services/recordTitle'
const props = defineProps({ modelValue: [String, Array], label: String, kind: String, doctype: String, businessDoctype: String, action: String, skill: String, multiple: Boolean, disabled: Boolean })
defineEmits(['update:modelValue'])
const captions = ref([])
const params = computed(() => ({kind: props.kind, doctype: props.doctype, business_doctype: props.businessDoctype, action: props.action, skill: props.skill}))
const caption = row => ({...row, label: readableName(row.label, props.label), description: [row.required ? 'Required' : '', row.description].filter(Boolean).join(' · ')})
let generation = 0
watch([() => props.modelValue, params], async () => {
  const current = ++generation
  const selected = (props.multiple ? props.modelValue || [] : [props.modelValue]).filter(Boolean)
  captions.value = selected.map(value => ({value, label: 'Saved selection'}))
  if (!selected.length) return
  try {
    const result = await coreApi('ai.configuration.editor_options', {...params.value, selected: JSON.stringify(selected)})
    if (current === generation) captions.value = selected.map(value => caption(result.items.find(row => row.value === value) || {value, label: 'Unavailable selection'}))
  } catch { /* The searchable picker exposes request errors; never display raw IDs. */ }
}, {immediate: true, deep: true})
const field = computed(() => ({label: props.label, readOnly: props.disabled, inlineResults: true, initialOptions: captions.value,
  search: async (query, signal) => (await coreApi('ai.configuration.editor_options', {...params.value, query}, false, {signal})).items.map(caption),
}))
</script>
<template><ChoiceField :field="field" :model-value="modelValue" :multiple="multiple" @update:model-value="$emit('update:modelValue', $event)" /></template>
