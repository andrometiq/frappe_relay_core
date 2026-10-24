<script setup>
import { onMounted, ref } from 'vue'
import { Badge, Button, ErrorMessage, FeatherIcon } from '@relay/ui'
import { coreApi, frappeRequest } from '../services/coreApi'
import { realtimeStatus } from '../services/realtime'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import LoadingRows from './LoadingRows.vue'
import WorkspaceHeading from './WorkspaceHeading.vue'
import WorkspaceState from './WorkspaceState.vue'
import { relativeTime } from './relativeTime'
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
      <WorkspaceHeading description="Monitor delivery, callback receipts and recovery in one place."><Button label="Refresh health" icon-left="refresh-cw" :loading="busy" @click="load" /></WorkspaceHeading>
      <ErrorMessage :message="error" />
      <LoadingRows v-if="busy && !callbacks && !recovery" :count="3" label="Reading health…" />
      <div class="v1-card-grid health-overview">
        <article class="workflow-card"><span><FeatherIcon name="radio" /> Live updates</span><Badge :label="realtimeStatus" :theme="realtimeStatus === 'Live' ? 'green' : 'amber'" /><p>Conversation updates use the socket connection.</p></article>
        <article class="workflow-card"><span><FeatherIcon name="alert-circle" /> Failed messages</span><strong>{{ busy || error ? '—' : failures.length + (failures.length === 50 ? '+' : '') }}</strong><p>In the latest accessible outgoing failures</p></article>
        <article class="workflow-card"><span><FeatherIcon name="refresh-cw" /> Recovery scheduling</span><Badge :label="recovery ? recovery.inactive ? 'Inactive' : 'Active' : 'Not checked'" :theme="recovery && !recovery.inactive ? 'green' : 'gray'" /><p>{{ recovery?.mode || 'Waiting for recovery status' }}</p></article>
      </div>
      <section class="workflow-card">
        <header class="card-heading"><h3>Callback receipt and projection</h3><Badge v-if="callbacks?.latest" :label="callbacks.latest.projection_status" :theme="callbacks.latest.projection_status === 'Failed' ? 'red' : 'gray'" /></header>
        <template v-if="callbacks">
          <p v-if="callbacks.latest" class="workspace-help">Latest authenticated callback <time :title="callbacks.latest.creation">{{ relativeTime(callbacks.latest.creation) }}</time></p>
          <p v-else class="workspace-help">No callback receipt is recorded for this account. A saved signing secret does not confirm delivery.</p>
          <article v-for="row in callbacks.items" :key="row.name" class="health-event"><FeatherIcon name="activity" /><a :href="'/desk/relay-hub-event/' + encodeURIComponent(row.name)">Review callback</a><Badge :label="row.projection_status" :theme="row.projection_status === 'Failed' ? 'red' : 'amber'" /><time :title="row.creation">{{ relativeTime(row.creation) }}</time></article>
          <p v-if="!callbacks.items.length" class="workspace-success"><FeatherIcon name="check" /> No failed or pending projections.</p><p v-if="callbacks.more" class="workspace-help">Showing the latest 50. Review earlier events in Desk.</p>
        </template>
        <a class="v1-link" href="#/contacts?tab=unlinked">Review unlinked / ambiguous senders <FeatherIcon name="arrow-up-right" /></a><p class="workspace-help">Hub forwarding attempts and callback acknowledgement errors are available in Hub’s delivery diagnostics.</p>
      </section>
      <section class="workflow-card"><header class="card-heading"><h3>Failed outgoing messages</h3><Badge v-if="failures.length" :label="String(failures.length)" theme="red" /></header><p class="workspace-help">Latest 50 accessible failures. Review delivery details before retrying.</p>
        <a v-for="row in failures" :key="row.name" :href="'#/messages?message=' + encodeURIComponent(row.name)" class="failure-row"><span class="failure-icon"><FeatherIcon name="alert-circle" :size="20" /></span><span class="failure-copy"><strong>{{ row.content || 'Failed message' }}</strong><small><Badge :label="row.status" theme="red" /><time :title="row.creation">{{ relativeTime(row.creation) }}</time></small></span><FeatherIcon name="chevron-right" /><span class="sr-only">Open conversation</span></a>
        <WorkspaceState v-if="!failures.length && !busy && !error" compact title="No failed outgoing messages" description="Delivery failures will appear here when they need your attention." icon="check"><a class="relay-button" href="#/messages">Open inbox</a></WorkspaceState>
      </section>
      <section v-if="recovery" class="workflow-card"><header class="card-heading"><h3>Recovery</h3><Badge :label="recovery.inactive ? 'Inactive' : 'Scheduling active'" :theme="recovery.inactive ? 'amber' : 'green'" /></header><p v-for="reason in recovery.reasons" :key="reason">{{ reason }}</p><div v-for="job in recovery.items.filter(row => ['Incoming event recovery', 'Message receipt recovery', 'Summary recovery'].includes(row.label))" :key="job.label" class="health-event"><FeatherIcon name="refresh-cw" /><strong>{{ job.label }}</strong><Badge :label="job.state" /><time :title="job.last_started">{{ relativeTime(job.last_started) || 'Never started' }}</time></div><p class="workspace-help">Checked {{ recovery.checked_at }}. A job starting does not confirm it completed.</p><a class="v1-link" href="/desk/scheduled-job-log">Review job logs in Desk <FeatherIcon name="arrow-up-right" /></a></section>
    </div>
  </section>
</template>
