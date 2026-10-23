<script setup>
import ChoiceField from './ChoiceField.vue'
import RemoteLinkField from './RemoteLinkField.vue'
defineProps({field:Object,modelValue:[String,Object,Array]})
defineEmits(['update:modelValue'])
</script>
<template><component :is="field.method ? RemoteLinkField : ChoiceField" :field="field" :model-value="modelValue" multiple @update:model-value="$emit('update:modelValue',$event)"/></template>
