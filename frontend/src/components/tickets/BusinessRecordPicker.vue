<script setup>
import { watch } from 'vue'
import RemoteLinkField from '../fields/RemoteLinkField.vue'

// A business type and one of its records the user's teams reach.
defineProps({ types: { type: Array, default: () => [] }, disabled: Boolean })
const type = defineModel('type', { type: String, default: '' })
const record = defineModel('record', { type: String, default: '' })
watch(type, () => { record.value = '' })
</script>

<template>
  <div class="business-record-picker">
    <select v-model="type" class="page-select" aria-label="Business type" :disabled="disabled">
      <option v-for="option in types" :key="option.value" :value="option.value">{{ option.label }}</option>
    </select>
    <RemoteLinkField v-if="type" :key="type" v-model="record" :field="{ label: '', method: 'api.business_records', params: { doctype: type }, placeholder: 'Search records…', readOnly: disabled }" />
  </div>
</template>

<style scoped>
.business-record-picker { display:grid; grid-template-columns:minmax(120px,auto) minmax(0,1fr); gap:8px; align-items:start; }
@media (max-width: 640px) {
  .business-record-picker { grid-template-columns:1fr; }
  .business-record-picker :deep(:is(input,select,button)) { min-height:44px; }
}
</style>
