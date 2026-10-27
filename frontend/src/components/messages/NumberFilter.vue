<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { FeatherIcon } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { watchRealtime } from '../../composables/useRealtimeRefresh'
import { numberFilterOptions } from '../../services/whatsappNumbers'
import NumberMenu from './NumberMenu.vue'

/** Inbox filter by the WhatsApp number a chat came to, with live chat counts per number. */
const props = defineProps({ numbers: { type: Array, required: true } })
const model = defineModel({ type: String, default: '' })
const counts = ref(null)
const options = computed(() => numberFilterOptions(props.numbers, counts.value))
const current = computed(() => options.value.find(option => option.value === model.value) || options.value[0])

async function loadCounts() {
  try { counts.value = await coreApi('queue_counts.numbers') } catch { counts.value = null }
}
const stop = watchRealtime(['Relay Message', 'Relay Conversation Assignment'], ['messages', 'inbox', 'contacts'], loadCounts)
loadCounts()
onBeforeUnmount(stop)
</script>

<template>
  <NumberMenu v-model="model" class="number-filter" title="WhatsApp number" hint="Show chats that came to one number" :options="options" divided>
    <template #default="{ open, toggle }">
      <button type="button" class="number-select" aria-haspopup="listbox" :aria-expanded="open" @click="toggle">
        <FeatherIcon name="message-circle" :size="14" class="number-wa" /><span class="number-select-lead">Number</span>
        <strong>{{ current.label }}</strong><FeatherIcon name="chevron-down" :size="14" class="number-caret" />
      </button>
    </template>
  </NumberMenu>
</template>
