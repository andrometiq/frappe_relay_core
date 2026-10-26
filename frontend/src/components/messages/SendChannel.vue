<script setup>
import { linkedTitle } from '../../services/linkedTitle';
import { computed, inject, ref } from 'vue';
import { Badge, Button, Dropdown } from '@relay/ui';
import { messagesKey } from '../../composables/messagesContext';
import { objectValue } from '../messageContent';
import { useEnabledChannels } from '../../composables/useEnabledChannels';
import { alsoSendChoices } from '../../services/enabledChannels';
const channelEnabled = useEnabledChannels();
const capabilities = inject('relayCapabilities', ref({}));
const props=defineProps({disabled:Boolean});
const {channels,channel,source,rows,busy,quoting,filterChannel,sendVia,alsoVia,toggleAlsoVia}=inject(messagesKey);
const sendChannel = computed(() => source.value?.channel || channel.value);
const choices = computed(() => {
  const found=new Map(channels.value.filter(row=>channelEnabled(row.label)).map(row=>[row.value,linkedTitle('Relay Channel', row.value, row.label)]));
  for (const row of [...rows.value,...(source.value?[source.value]:[])]) {
    const provider=objectValue(row.provider_context).provider;
    if(row.channel&&!found.has(row.channel)&&channelEnabled(provider))found.set(row.channel,row.channel_title || provider || 'Channel');
  }
  return found;
});
const alsoChoices = computed(() => alsoSendChoices(capabilities.value, choices.value, sendChannel.value));
const sendLabel = computed(() => [choices.value.get(sendChannel.value) || source.value?.channel_title || 'Choose a channel',
  ...alsoChoices.value.filter(([value])=>alsoVia.value.includes(value)).map(([,label])=>label)].join(' + '));
const locked = computed(() => props.disabled || busy.value || quoting.value);
const options = computed(() => [
  ...[...choices.value].map(([value,label])=>({label,icon:value===sendChannel.value?'check':undefined,onClick:()=>sendVia(value)})),
  ...alsoChoices.value.map(([value,label])=>({label:'Also send via '+label,icon:alsoVia.value.includes(value)?'check-square':'square',onClick:()=>toggleAlsoVia(value)})),
  // A saved channel filter from older views can still be cleared so every channel shows again.
  ...(channel.value?[{label:'Show all channels',icon:'list',onClick:()=>filterChannel('')}]:[]),
].map(row=>({...row,disabled:locked.value})));
</script>
<template>
  <Badge v-if="!choices.size" label="No channel" />
  <div v-else class="send-via">
    <span class="send-via__caption">Send via</span>
    <Dropdown :options="options">
      <Button :label="sendLabel" icon-right="chevron-down"
        :disabled="locked" :title="'Send via ' + sendLabel" :aria-label="'Send via ' + sendLabel" />
    </Dropdown>
  </div>
</template>
