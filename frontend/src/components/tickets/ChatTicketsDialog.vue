<script setup>
import { computed, ref, watch } from 'vue'
import { Dialog, ErrorMessage, FormControl } from '@relay/ui'
import ChatTicketRow from './ChatTicketRow.vue'
import ChoiceField from '../fields/ChoiceField.vue'
import RemoteLinkField from '../fields/RemoteLinkField.vue'
import { coreApi } from '../../services/coreApi'
import { chatTicketsStore, emptyChatTicketFilters, hasChatTicketFilters } from '../../services/chatTickets'
import { pickerOptions } from '../../services/ticketSettings'
import { useTicketSettings } from '../../composables/useTicketSettings'
import { useDebouncedSearch } from '../../composables/useDebouncedSearch'
import { useLoadMore } from '../../composables/useLoadMore'
// Every ticket of one chat, 20 at a time as the list scrolls, filtered by status, owner, type and words.
const open = defineModel({ type: Boolean, default: false })
const props = defineProps({ contact: { type: String, required: true } })
const { settings } = useTicketSettings()
const { items, next, busy, error, open: show, more } = chatTicketsStore(coreApi)
const filters = ref(emptyChatTicketFilters()), query = ref('')
const statusField = computed(() => ({ label: 'Status', placeholder: 'Any status', options: pickerOptions(settings.value.statuses) }))
const typeOptions = computed(() => pickerOptions(settings.value.types, 'Any type'))
const ownerField = { label: 'Assigned to', placeholder: 'Anyone', method: 'tickets.colleagues', params: { mention: 1 } }
const reload = () => show(props.contact, { ...filters.value, query: query.value })
watch(filters, reload, { deep: true, immediate: true })
useDebouncedSearch(query, reload)
const root = ref(null)
const sentinel = useLoadMore({ root, loading: busy, hasMore: () => !!next.value, error, load: more })
const clear = () => { filters.value = emptyChatTicketFilters(); query.value = '' }
</script>

<template>
  <Dialog v-model="open" :options="{ title: 'Tickets of this chat', size: 'xl' }">
    <div class="chat-ticket-filters">
      <FormControl v-model="query" class="chat-ticket-search" type="search" label="Search" placeholder="Words in the subject or description" maxlength="80" />
      <ChoiceField v-model="filters.statuses" multiple :field="statusField" />
      <RemoteLinkField v-model="filters.assignedTo" :field="ownerField" />
      <FormControl v-if="settings.types.length" v-model="filters.ticketType" type="select" label="Type" :options="typeOptions" />
      <button v-if="hasChatTicketFilters({ ...filters, query })" type="button" class="chat-ticket-clear" @click="clear">Clear filters</button>
    </div>
    <ErrorMessage :message="error" />
    <div ref="root" class="chat-ticket-results" :aria-busy="busy ? 'true' : undefined">
      <ul v-if="items.length" class="chat-ticket-list"><ChatTicketRow v-for="ticket in items" :key="ticket.name" :ticket="ticket" :settings="settings" /></ul>
      <p v-else-if="busy" class="chat-ticket-empty" role="status">Loading tickets…</p>
      <p v-else-if="!error" class="chat-ticket-empty">{{ hasChatTicketFilters({ ...filters, query }) ? 'No tickets match these filters.' : 'No tickets for this chat.' }}</p>
      <div v-if="next" ref="sentinel" class="chat-ticket-sentinel" aria-hidden="true" />
    </div>
  </Dialog>
</template>

<style scoped>
.chat-ticket-filters { display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); align-items:end; gap:10px; margin-bottom:12px; }
.chat-ticket-search { grid-column:1 / -1; }
.chat-ticket-clear { justify-self:start; padding:6px 0; border:0; background:none; color:var(--relay-accent-text); font-size:13px; cursor:pointer; }
.chat-ticket-results { max-height:min(60vh, 520px); overflow-y:auto; border:1px solid var(--relay-stroke); border-radius:8px; }
.chat-ticket-list { margin:0; padding:0; }
.chat-ticket-empty { margin:0; padding:24px; color:var(--relay-ink-3); font-size:13px; text-align:center; }
.chat-ticket-sentinel { height:1px; }
</style>
