<script setup>
import { computed, inject } from 'vue'
import { FeatherIcon } from '@relay/ui'
import { messagesKey } from '../../composables/messagesContext'
import { sendNumbersKey } from '../../composables/useSendNumbers'
import NumberMenu from './NumberMenu.vue'

/** "Send via" WhatsApp number picker of the composer on a site with several numbers. */
const { busy: working, sending, quoting } = inject(messagesKey)
const busy = computed(() => working.value || sending.value > 0)
const numbers = inject(sendNumbersKey)
const selected = computed({ get: () => numbers.current.value, set: value => numbers.pick(value) })
</script>

<template>
  <NumberMenu v-model="selected" class="send-number" title="Send via" placement="above" :options="numbers.choices.value"
    hint="Replies go from the number the customer wrote to, unless you change it." :disabled="busy || quoting">
    <template #default="{ open, toggle }">
      <button type="button" class="send-number-button" aria-haspopup="listbox" :aria-expanded="open" :disabled="busy || quoting"
        :aria-label="'Send via ' + (numbers.chosen.value?.label || 'WhatsApp number')" @click="toggle">
        <span class="send-number-lead">Send via</span>
        <span class="send-number-pill"><FeatherIcon name="message-circle" :size="14" class="number-wa" /><strong>{{ numbers.chosen.value?.label || 'Choose a number' }}</strong>
          <span v-if="numbers.chosen.value?.address" class="send-number-address">{{ numbers.chosen.value.address }}</span>
          <FeatherIcon name="chevron-down" :size="13" class="number-caret" /></span>
      </button>
    </template>
  </NumberMenu>
</template>

<style scoped>
.send-number-button { min-height:44px; }
.send-number-address { display:none; }
@media (min-width:769px) { .send-number-address { display:inline; } }
</style>
