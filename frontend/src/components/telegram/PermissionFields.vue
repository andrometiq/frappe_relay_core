<script setup>
import { permissionLabel } from "../../services/telegramPermissions";
const props = defineProps({rights:Array,disabled:Boolean});
const model = defineModel({default:()=>({})});
</script>
<template>
  <fieldset :disabled="disabled" class="grid grid-cols-1 sm:grid-cols-2 gap-2">
    <label v-for="right in rights" :key="right" class="flex gap-2 items-center text-sm"><input type="checkbox" :checked="model[right] === true" @change="model={...model,[right]:$event.target.checked}" />{{ permissionLabel(right) }}</label>
  </fieldset>
</template>
