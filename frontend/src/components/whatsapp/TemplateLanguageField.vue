<script setup>
import { computed, ref } from 'vue'
import { FormControl } from '@relay/ui'
import RelaySelect from '../RelaySelect.vue'
import { templateLanguages } from '../../services/templateLanguages'
const props=defineProps({modelValue:String,disabled:Boolean})
const emit=defineEmits(['update:modelValue'])
const custom=ref(false)
const options=computed(()=>[...templateLanguages(props.modelValue),{value:'__custom',label:'Another language code…'}])
function select(value){if(value==='__custom'){custom.value=true;return}custom.value=false;emit('update:modelValue',value)}
</script>
<template>
 <div class="space-y-2">
  <RelaySelect label="Language" :model-value="custom?'__custom':modelValue" :options="options" :disabled="disabled" @update:model-value="select" />
  <FormControl v-if="custom" label="Provider language code" :model-value="modelValue" :disabled="disabled" placeholder="For example: ta" @update:model-value="emit('update:modelValue',$event)" />
 </div>
</template>
