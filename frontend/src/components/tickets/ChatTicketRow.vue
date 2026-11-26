<script setup>
import { computed } from 'vue'
import { Badge } from '@relay/ui'
import { linkedTitle } from '../../services/linkedTitle'
import { recordTitle } from '../../services/recordTitle'
import { statusLook } from '../../services/ticketSettings'
import { ticketRoute } from '../../services/ticketForm'
import { dateTime, listTime } from '../relativeTime'
// One ticket of a chat; it opens the ticket as the Tickets page does.
const props = defineProps({ ticket: { type: Object, required: true }, settings: { type: Object, required: true } })
const look = computed(() => statusLook(props.settings, props.ticket))
</script>

<template>
  <li class="chat-ticket">
    <a :href="ticketRoute(ticket.name)" class="chat-ticket-link">
      <span class="chat-ticket-copy">
        <b>{{ recordTitle(ticket, 'Ticket') }}</b>
        <small>{{ ticket.assigned_to ? linkedTitle('User', ticket.assigned_to) : 'Unassigned' }} · <time :datetime="ticket.creation" :title="dateTime(ticket.creation)">{{ listTime(ticket.creation) }}</time></small>
      </span>
      <Badge :label="look.label" :theme="look.theme" />
    </a>
  </li>
</template>

<style scoped>
.chat-ticket { list-style:none; border-top:1px solid var(--relay-stroke); }
.chat-ticket:first-child { border-top:0; }
.chat-ticket-link { display:flex; align-items:center; gap:10px; min-height:44px; padding:6px 12px; color:inherit; text-decoration:none; }
.chat-ticket-link:hover { background:var(--relay-hover); }
.chat-ticket-copy { display:flex; flex:1; flex-direction:column; min-width:0; }
.chat-ticket-copy b, .chat-ticket-copy small { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.chat-ticket-copy b { color:var(--relay-ink); font-size:13px; font-weight:600; }
.chat-ticket-copy small { color:var(--relay-ink-3); font-size:12px; }
</style>
