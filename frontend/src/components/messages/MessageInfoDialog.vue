<script setup>
import { computed } from 'vue'
import { Dialog } from '@relay/ui'
import ParticipantReceipts from './ParticipantReceipts.vue'
import { objectValue } from '../messageContent'
import { channelStatus } from '../../services/channelComposition'
import { deliveryReason } from '../../services/deliveryReason'
import { dateTime as when } from '../relativeTime'

// Sent, Delivered and Read with time and person, then who in the team saw the message.
const props = defineProps({ info: Object, coverage: Object, coverageError: String, contactName: String, receipts: Boolean, groupReceipts: Boolean })
const open = defineModel({ type: Boolean })
const outgoing = computed(() => props.info?.direction === 'Outgoing')
const person = computed(() => props.contactName || 'Customer')
const failed = computed(() => ['Failed', 'Rejected'].includes(props.info?.status))
// Provider receipt times come with the read coverage; an old receipt has none and shows only its state.
const rows = computed(() => {
  const info = props.info, times = props.coverage?.receipt_times || {}, sent = when(info.sent_at || info.creation)
  if (!outgoing.value) return [{ label: 'Received', value: sent, who: 'From ' + person.value }]
  if (!props.receipts) return [{ label: 'Sent', value: sent, who: 'To ' + person.value }, { label: 'Status', value: channelStatus(info) }]
  const delivered = ['Delivered', 'Read'].includes(info.status), read = info.status === 'Read'
  return [
    { label: 'Sent', value: when(times.Sent) || sent, who: 'To ' + person.value },
    { label: 'Delivered', value: failed.value ? 'Not delivered' : delivered ? when(times.Delivered) || 'Delivered' : 'Not yet', who: delivered ? person.value : '' },
    { label: 'Read', value: read ? when(times.Read) || 'Read' : 'Not yet', who: read ? person.value : '' },
  ]
})
const seen = computed(() => props.coverage?.read_by || [])
const waiting = computed(() => (props.coverage?.unread_by || []).map(reader => reader.full_name).join(', '))
</script>

<template>
  <Dialog v-model="open" :options="{ title: 'Message info', size: 'md' }">
    <div v-if="info" class="message-info">
      <blockquote class="message-info-content">{{ info.content || 'Attachment' }}</blockquote>
      <dl class="message-info-grid">
        <div v-for="row in rows" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value || '—' }}<small v-if="row.who">{{ row.who }}</small></dd></div>
        <div v-if="failed"><dt>Reason</dt><dd>{{ deliveryReason(info.delivery_error) }}<small v-if="info.delivery_error && info.delivery_error !== deliveryReason(info.delivery_error)">{{ info.delivery_error }}</small></dd></div>
        <div v-if="info.edited_at"><dt>Edited</dt><dd>{{ when(info.edited_at) }}</dd></div>
      </dl>
      <ParticipantReceipts v-if="outgoing && groupReceipts && objectValue(info.provider_context).group_id" :message="info.name" />
      <h3 class="message-info-heading">Seen by your team</h3>
      <p v-if="coverageError" role="alert">{{ coverageError }}</p>
      <dl v-else-if="coverage" class="message-info-grid">
        <div v-for="reader in seen" :key="reader.user"><dt>{{ reader.full_name }}</dt><dd>{{ when(reader.read_at) }}</dd></div>
        <p v-if="!seen.length" class="message-info-empty">No one yet</p>
        <div v-if="waiting"><dt>Not seen yet</dt><dd>{{ waiting }}</dd></div>
      </dl>
    </div>
  </Dialog>
</template>

<style scoped>
.message-info { display:flex; flex-direction:column; gap:12px; font-size:13px; }
.message-info-content { margin:0; padding:8px 10px; border-left:3px solid var(--outline-gray-3); border-radius:4px; background:var(--surface-gray-1); white-space:pre-wrap; overflow-wrap:anywhere; max-height:160px; overflow:auto; }
.message-info-grid { display:grid; gap:8px; margin:0; }
.message-info-grid > div { display:grid; grid-template-columns:120px minmax(0,1fr); gap:12px; }
.message-info-grid dt { color:var(--ink-gray-5); }
.message-info-grid dd { display:flex; flex-wrap:wrap; gap:0 8px; margin:0; color:var(--ink-gray-8); overflow-wrap:anywhere; }
.message-info-grid small { color:var(--ink-gray-5); font-size:12px; }
.message-info-heading { margin-top:4px; font-size:13px; font-weight:600; }
.message-info-empty { color:var(--ink-gray-5); }
</style>
