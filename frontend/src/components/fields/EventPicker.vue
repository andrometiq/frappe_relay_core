<script setup>
import { computed, ref, watch } from 'vue'
import { Button, ErrorMessage } from '@relay/ui'
import ChoiceField from './ChoiceField.vue'
import { coreApi } from '../../services/coreApi'
import { pickerError } from '../../services/pickerError'
import { readableName } from '../../services/recordTitle'
const props = defineProps({ method: { type: String, default: 'ai.configuration.editor_options' }, modelValue: [String, Array], label: String, kind: String, doctype: String, businessDoctype: String, action: String, skill: String, multiple: Boolean, disabled: Boolean })
defineEmits(['update:modelValue'])
const managed = ref(false)
const captions = ref([]), error = ref(''), loading = ref(false)
const params = computed(() => ({kind: props.kind, doctype: props.doctype, business_doctype: props.businessDoctype, action: props.action, skill: props.skill}))
const caption = row => ({...row, label: readableName(row.label, props.label), description: [row.required ? 'Required' : '', row.description].filter(Boolean).join(' · ')})
let generation = 0
async function loadCaptions() {
  const current = ++generation
  error.value = ''; loading.value = false; managed.value = false
  const selected = (props.multiple ? props.modelValue || [] : [props.modelValue]).filter(Boolean)
  captions.value = selected.map(value => ({value, label: 'Saved selection'}))
  if (!selected.length && props.kind !== 'model') return
  loading.value = true
  try {
    const result = await coreApi(props.method, {...params.value, selected: JSON.stringify(selected)})
    if (current === generation) {
      managed.value = Boolean(result.read_only)
      captions.value = selected.map(value => caption(result.items.find(row => row.value === value) || {value, label: 'Unavailable selection'}))
    }
  } catch (e) {
    if (current === generation) {
      captions.value = selected.map(value => ({value, label: 'Unavailable selection'}))
      error.value = pickerError(props.label, true)
    }
  } finally { if (current === generation) loading.value = false }
}
watch([() => props.modelValue, params, () => props.method], loadCaptions, {immediate: true, deep: true})
const search = computed(() => {
  const values = params.value, method = props.method
  return async (query, signal) => (await coreApi(method, {...values, query}, false, {signal})).items.map(caption)
})
const field = computed(() => ({label: props.label, readOnly: props.disabled || managed.value || (props.kind === 'model' && loading.value), initialOptions: captions.value,
  search: search.value, errorMessage: pickerError(props.label),
}))
</script>
<template><div class="event-picker"><ChoiceField :field="field" :model-value="modelValue" :multiple="multiple" @update:model-value="$emit('update:modelValue', $event)" /><p v-if="managed" class="text-sm text-ink-gray-5">Managed by your administrator.</p><ErrorMessage :message="error" /><Button v-if="error" label="Retry saved selection" variant="ghost" :loading="loading" @click="loadCaptions" /></div></template>
<style scoped>
.event-picker{min-width:0;display:grid;gap:6px;align-content:start}
</style>
