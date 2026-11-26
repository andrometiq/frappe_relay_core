<script setup>
import { defineAsyncComponent, ref, watch } from 'vue'
import { Button, ErrorMessage } from '@relay/ui'
import ChatTicketRow from './ChatTicketRow.vue'
import { coreApi } from '../../services/coreApi'
import { CHAT_TICKET_PREVIEW, chatTicketsStore } from '../../services/chatTickets'
import { useTicketSettings } from '../../composables/useTicketSettings'
import { useRealtimeRefresh } from '../../composables/useRealtimeRefresh'
const ChatTicketsDialog = defineAsyncComponent(() => import('./ChatTicketsDialog.vue'))
// The newest tickets of the open chat, so staff need not open the Tickets page; "View all" pages and filters them.
const props = defineProps({ contact: { type: String, required: true } })
const { settings, load: loadSettings } = useTicketSettings()
const { items, next, busy, error, open, load } = chatTicketsStore(coreApi, CHAT_TICKET_PREVIEW)
const all = ref(false)
watch(() => props.contact, contact => { open(contact) }, { immediate: true })
loadSettings().catch(() => {})
useRealtimeRefresh(['Relay Ticket'], ['tickets'], () => load())
</script>

<template>
  <section class="chat-tickets" aria-label="Tickets">
    <h3><button type="button" class="chat-tickets-heading" @click="all = true">Tickets</button>
      <Button v-if="items.length" label="View all" variant="ghost" size="sm" @click="all = true" /></h3>
    <ErrorMessage :message="error" />
    <p v-if="busy && !items.length" class="chat-tickets-empty" role="status">Loading tickets…</p>
    <p v-else-if="!items.length && !error" class="chat-tickets-empty">No tickets for this chat.</p>
    <ul v-if="items.length" class="chat-tickets-list"><ChatTicketRow v-for="ticket in items" :key="ticket.name" :ticket="ticket" :settings="settings" /></ul>
    <button v-if="next" type="button" class="chat-tickets-more" @click="all = true">More tickets</button>
    <ChatTicketsDialog v-if="all" v-model="all" :contact="contact" />
  </section>
</template>

<style scoped>
.chat-tickets { display:flex; flex-direction:column; gap:4px; padding:12px 16px; border-bottom:1px solid var(--relay-stroke); }
.chat-tickets h3 { display:flex; align-items:center; justify-content:space-between; margin:0 0 4px; }
.chat-tickets-heading { padding:0; border:0; background:none; color:var(--relay-ink-soft); font-size:11.5px; font-weight:600; cursor:pointer; }
.chat-tickets-list { margin:0 -12px; padding:0; }
.chat-tickets-empty { margin:0; color:var(--relay-ink-3); font-size:12.5px; }
.chat-tickets-more { align-self:flex-start; padding:4px 0; border:0; background:none; color:var(--relay-accent-text); font-size:12.5px; cursor:pointer; }
</style>
