<script setup>
import { computed, inject } from 'vue';
import { Badge, Button, Dropdown } from '@relay/ui';
import { messagesKey } from '../../composables/messagesContext';
import { objectValue } from '../messageContent';
const props=defineProps({disabled:Boolean});
const {channels,channel,source,rows,busy,quoting,filterChannel}=inject(messagesKey);
const options=computed(() => {
  const choices=new Map(channels.value.map(row=>[row.value,{value:row.value,label:row.label + (row.unread ? ` · ${row.unread} unread` : '')}]));
  for (const row of [...rows.value,...(source.value?[source.value]:[])]) {
    if(row.channel&&!choices.has(row.channel))choices.set(row.channel,{value:row.channel,label:objectValue(row.provider_context).provider||row.channel});
  }
  return [{value:'',label:'All channels'},...choices.values()].map(row=>({label:row.label,onClick:()=>filterChannel(row.value),disabled:props.disabled||busy.value||quoting.value}));
});
</script>
<template>
  <Badge v-if="options.length <= 1" label="No channel" />
  <Dropdown v-else :options="options">
    <Button :label="channels.find(row => row.value === channel)?.label || 'All channels'" icon-right="chevron-down"
      :disabled="disabled || busy || quoting" title="Filter channel" aria-label="Filter channel" />
  </Dropdown>
</template>
