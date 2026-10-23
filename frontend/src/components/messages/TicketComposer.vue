<script setup>
import { ref } from 'vue'
import { Button } from '@relay/ui'
import RelayForm from '../RelayForm.vue'
import { coreApi } from '../../services/coreApi'
import { useTask } from '../../composables/useTask'
const props=defineProps({messages:Array}),emit=defineEmits(['close','created','remove'])
const {busy,error,run}=useTask(),draft=ref({subject:'',brief:'',category:'Query'})
const fields=[{name:'subject',label:'Ticket subject',type:'Data',required:true,maxLength:140,wide:true},{name:'category',label:'Category',type:'Select',options:['Query','Payment evidence','Support','Other'],required:true},{name:'brief',label:'Brief',type:'Small Text',maxLength:4000,wide:true}]
async function save(){const ticket=await coreApi('tickets.create',{...draft.value,messages:props.messages.map(message=>message.name)},true);emit('created',ticket)}
</script>
<template><section class="workflow-card m-3 max-h-[50vh] overflow-auto" aria-label="Create ticket"><div class="flex justify-between"><h3 class="font-semibold">Create ticket · {{messages.length}} messages</h3><Button label="Cancel ticket" :disabled="busy" @click="emit('close')"/></div><div class="flex flex-wrap gap-2"><Button v-for="message in messages" :key="message.name" :label="'Remove '+message.name" :disabled="busy" @click="emit('remove',message.name)"/></div><RelayForm v-model="draft" :fields="fields" label="Create ticket" :busy="busy||!messages.length" :error="error" @submit="run(save)"/></section></template>