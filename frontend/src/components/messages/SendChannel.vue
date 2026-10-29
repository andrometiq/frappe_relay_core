<script setup>
import { Badge, Button, Dropdown } from '@relay/ui';
import { useSendChannel } from '../../composables/useSendChannel';
const props = defineProps({ disabled: Boolean });
const { choices, sendLabel, locked, options } = useSendChannel(() => props.disabled);
</script>
<template>
  <Badge v-if="!choices.size" label="No channel" />
  <Dropdown v-else-if="choices.size > 1" :options="options" placement="top" touch-targets>
    <Button class="send-via-chip" icon="message-circle" :label="sendLabel" variant="ghost"
      :disabled="locked" :title="'Send via ' + sendLabel" :aria-label="'Send via ' + sendLabel" />
  </Dropdown>
</template>

<style scoped>
.send-via-chip.relay-button { min-height:44px; height:auto; }
</style>
