<script setup>
import { computed, inject } from 'vue';
import { Badge, Button, Dropdown } from '@relay/ui';
import { messagesKey } from '../../composables/messagesContext';
import { objectValue } from '../messageContent';
const props=defineProps({disabled:Boolean,whatsappOnly:Boolean});
const {channels,source,rows,busy,quoting,filterChannel}=inject(messagesKey);
const options=computed(() => {
  const choices=new Map(channels.value.filter(row=>!props.whatsappOnly||row.label==='WhatsApp'||row.provider==='WhatsApp').map(row=>[row.value,{value:row.value,label:row.label}]));
  for (const row of [...rows.value,...(source.value?[source.value]:[])]) {
    if(props.whatsappOnly && objectValue(row.provider_context).provider!=='WhatsApp')continue;
    if(row.channel&&!choices.has(row.channel))choices.set(row.channel,{value:row.channel,label:objectValue(row.provider_context).provider||row.channel});
  }
  return [...choices.values()].map(row=>({label:row.label,onClick:()=>filterChannel(row.value),disabled:props.disabled||busy.value||quoting.value}));
});
</script>
<template>
  <Badge v-if="options.length <= 1" label="WhatsApp" theme="green" />
  <Dropdown v-else :options="options">
    <Button :label="objectValue(source?.provider_context).provider || 'Send via'" icon-right="chevron-down"
      :disabled="disabled || busy || quoting" title="Send via" aria-label="Send via" />
  </Dropdown>
</template>
