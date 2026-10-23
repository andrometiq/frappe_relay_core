<script setup>
import { onMounted, ref } from 'vue'
import { Badge, Button, ErrorMessage } from '@relay/ui'
import { coreApi, frappeRequest } from '../services/coreApi'
import { realtimeStatus } from '../services/realtime'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import DeliveryWorkspace from './DeliveryWorkspace.vue'
const tab = ref('health'), recovery = ref(null), callbacks = ref(null), failures = ref([]), busy = ref(false), error = ref('')
let refreshPending = false
async function load() {
  if (busy.value) { refreshPending = true; return }
  busy.value = true; error.value = ''
  const results = await Promise.allSettled([
    coreApi('operations.recovery_status'), coreApi('operations.callback_status'),
    frappeRequest('frappe.client.get_list', { doctype: 'Relay Message', fields: JSON.stringify(['name', 'relay_contact', 'status', 'creation', 'content']), filters: JSON.stringify({ direction: 'Outgoing', status: 'Failed', provider_context: ['like', '%WhatsApp%'] }), order_by: 'creation desc', limit_page_length: 50 }),
  ])
  const targets = [recovery, callbacks, failures]
  results.forEach((result, index) => { if (result.status === 'fulfilled') targets[index].value = result.value; else error.value += result.reason.message + '\n' })
  busy.value = false
  if (refreshPending) { refreshPending = false; await load() }
}
onMounted(load)
useRealtimeRefresh(['Relay Message', 'Relay Hub Event'], ['messages', 'incoming'], load)
</script>
<template>
  <section class="v1-screen">
    <nav class="v1-tabs" aria-label="Activity sections"><Button label="Health & failures" :variant="tab === 'health' ? 'solid' : 'ghost'" @click="tab = 'health'" /><Button label="Delivery & uncertain sends" :variant="tab === 'delivery' ? 'solid' : 'ghost'" @click="tab = 'delivery'" /></nav>
    <DeliveryWorkspace v-if="tab === 'delivery'" />
    <div v-else class="v1-content space-y-5">
      <div class="flex flex-wrap items-center gap-3"><h2 class="text-lg font-semibold">Activity & health</h2><Badge :label="'Socket: ' + realtimeStatus" /><Button label="Refresh health" :loading="busy" @click="load" /></div>
      <ErrorMessage :message="error" /><p v-if="busy" role="status">Reading health…</p>
      <section class="workflow-card"><h3 class="font-semibold">Callback receipt and projection</h3><template v-if="callbacks"><p v-if="callbacks.latest">Latest authenticated callback: {{ callbacks.latest.creation }} · {{ callbacks.latest.projection_status }}</p><p v-else>No callback receipt is recorded for this account. A saved signing secret does not confirm delivery.</p><article v-for="row in callbacks.items" :key="row.name" class="flex flex-wrap justify-between gap-3 border-t pt-3"><a class="underline" :href="'/desk/relay-hub-event/' + encodeURIComponent(row.name)">{{ row.name }}</a><span>{{ row.projection_status }} · {{ row.creation }}</span></article><p v-if="!callbacks.items.length">No failed or pending projections.</p><p v-if="callbacks.more">Showing the latest 50. Review earlier events in Desk.</p></template><a class="v1-link" href="#/contacts?tab=unlinked">Review unlinked / ambiguous senders</a><p class="text-sm text-ink-gray-5">Hub forwarding attempts and callback acknowledgement errors are available in Hub’s delivery diagnostics.</p></section>
      <section class="workflow-card"><h3 class="font-semibold">Failed outgoing messages</h3><p class="text-sm text-ink-gray-5">Latest 50 accessible failures. Open the conversation to review its delivery details before retrying.</p><a v-for="row in failures" :key="row.name" :href="'#/messages?message=' + encodeURIComponent(row.name)" class="v1-list-card"><strong>{{ row.content || row.name }}</strong><span>{{ row.status }} · {{ row.creation }}</span><span class="underline">Open conversation</span></a><p v-if="!failures.length && !busy && !error">No failed outgoing messages.</p></section>
      <section v-if="recovery" class="workflow-card"><h3 class="font-semibold">Recovery</h3><p>{{ recovery.mode }} · {{ recovery.inactive ? 'Inactive' : 'Scheduling active' }}</p><p v-for="reason in recovery.reasons" :key="reason">{{ reason }}</p><div v-for="job in recovery.items.filter(row => ['Incoming event recovery', 'Message receipt recovery', 'Summary recovery'].includes(row.label))" :key="job.label" class="flex flex-wrap justify-between gap-3 border-t pt-3"><strong>{{ job.label }}</strong><span>{{ job.state }} · {{ job.last_started || 'Never started' }}</span></div><p class="text-sm text-ink-gray-5">Checked {{ recovery.checked_at }}. A job starting does not confirm it completed.</p><a class="v1-link" href="/desk/scheduled-job-log">Review job logs in Desk</a></section>
    </div>
  </section>
</template>
