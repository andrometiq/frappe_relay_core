<script setup>
import { linkedTitle } from '../../services/linkedTitle';
import { computed, inject } from 'vue';
import { Badge, Button, Dropdown } from '@relay/ui';
import { messagesKey } from '../../composables/messagesContext';
import { objectValue } from '../messageContent';
const props=defineProps({disabled:Boolean});
const {channels,channel,source,rows,busy,quoting,filterChannel}=inject(messagesKey);
const sendChannel = computed(() => source.value?.channel || channel.value);
const sendLabel = computed(() => sendChannel.value
  ? linkedTitle('Relay Channel', sendChannel.value, source.value?.channel_title || channels.value.find(row => row.value === sendChannel.value)?.label || 'Channel')
  : 'Choose a channel');
const options=computed(() => {
  const choices=new Map(channels.value.map(row=>[row.value,{value:row.value,label:linkedTitle('Relay Channel', row.value, row.label) + (row.unread ? ` · ${row.unread} unread` : '')}]));
  for (const row of [...rows.value,...(source.value?[source.value]:[])]) {
    if(row.channel&&!choices.has(row.channel))choices.set(row.channel,{value:row.channel,label:row.channel_title || objectValue(row.provider_context).provider || 'Channel'});
  }
  return [{value:'',label:'View all channels'},...choices.values()].map(row=>({label:row.label,onClick:()=>filterChannel(row.value),disabled:props.disabled||busy.value||quoting.value}));
});
</script>
<template>
  <Badge v-if="options.length <= 1" label="No channel" />
  <Dropdown v-else :options="options">
    <Button :label="sendLabel" icon-right="chevron-down"
      :disabled="disabled || busy || quoting" :title="'Reply channel: ' + sendLabel" :aria-label="'Reply channel: ' + sendLabel" />
  </Dropdown>
</template>
