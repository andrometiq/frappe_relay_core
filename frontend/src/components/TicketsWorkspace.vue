<script setup>
import { useLoadMore } from '../composables/useLoadMore'
import ChoiceField from './fields/ChoiceField.vue'
import { useDebouncedSearch } from '../composables/useDebouncedSearch'
import { recordTitle } from '../services/recordTitle'
import { linkedTitle } from '../services/linkedTitle'
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { Badge, Button, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi, frappeRequest } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import WorkspaceHeading from './WorkspaceHeading.vue'
import TicketDiscussion from './TicketDiscussion.vue'
import RemoteLinkField from './fields/RemoteLinkField.vue'
import WorkspaceState from './WorkspaceState.vue'
import LoadingRows from './LoadingRows.vue'
import { relativeTime } from './relativeTime'
import { closeRoute, openRoute } from '../useViewRoute'
const capabilities = inject('relayCapabilities', ref({}))
const aiEnabled = computed(() => Boolean(capabilities.value?.ai))
const businessTypes = ref([])
const filters = ref({ business_doctype: '', business_name: '', assigned_to: '', status: '', category: '', mine: '' })
const page = ref({ items: [] }), selected = ref(null), owner = ref(''), error = ref(''), feedback = ref('')
const history = ref({ items: [] }), transcript = ref({ items: [] }), deliveries = ref({ items: [] })
const listBusy = ref(false), detailBusy = ref(false), saving = ref(false)
const busy = computed(() => listBusy.value || detailBusy.value || saving.value)
const staffTookOver = computed(() => selected.value?.ai_disabled && selected.value?.ownership_actor && selected.value.ownership_actor !== 'Administrator')
let generation = 0, detailGeneration = 0
async function refreshWindow(method, loaded, name, request) {
  const boundary = loaded.items.at(-1)?.name
  const items = []
  let cursor = {}, result
  do {
    result = await coreApi('tickets.' + method, { name, ...cursor })
    if (request !== detailGeneration) return null
    items.push(...result.items)
    cursor = result.next
  } while (cursor && boundary && !items.some(row => row.name === boundary))
  return { items, next: result.next }
}
async function detail(name) {
  const request = ++detailGeneration; detailBusy.value = true
  try {
    const [ticket, messages, ai, sent] = await Promise.all([
      coreApi('tickets.read', { name }), refreshWindow('transcript', transcript.value, name, request),
      aiEnabled.value ? refreshWindow('ai_history', history.value, name, request) : { items: [] }, refreshWindow('deliveries', deliveries.value, name, request),
    ])
    if (request !== detailGeneration || selected.value?.name !== name) return
    if (owner.value === (selected.value.assigned_to || '')) owner.value = ticket.assigned_to || ''
    selected.value = ticket; transcript.value = messages; history.value = ai; deliveries.value = sent
  } catch (e) {
    if (request === detailGeneration) { close(); error.value = e.message }
  } finally { if (request === detailGeneration) detailBusy.value = false }
}
async function load(cursor = {}) {
  const request = ++generation; listBusy.value = true; error.value = ''
  try {
    const [result] = await Promise.all([
      coreApi('tickets.directory', { ...filters.value, ...cursor }),
      selected.value ? detail(selected.value.name) : Promise.resolve(),
    ])
    if (request === generation) page.value = { ...result, items: cursor.after ? [...page.value.items, ...result.items] : result.items }
  } catch (e) { if (request === generation) error.value = e.message }
  finally { if (request === generation) listBusy.value = false }
}
function reset() { filters.value = { business_doctype: '', business_name: '', assigned_to: '', status: '', category: '', mine: '' } }
function status(value) { filters.value.status = value }
function mine(value) { filters.value.mine = filters.value.mine === value ? '' : value }
async function searchAssignees(query, signal) {
  const rows = await frappeRequest('frappe.desk.search.search_link', {doctype:'User', txt:query, filters:JSON.stringify({enabled:1}), page_length:30}, false, {signal})
  return rows.map(row => ({value:row.value, label:recordTitle(row, 'User')}))
}
const assigneeField = computed(() => ({label:'Assignee', search:searchAssignees,
  initialOptions: filters.value.assigned_to ? [{value:filters.value.assigned_to, label:linkedTitle('User', filters.value.assigned_to)}] : [],
}))
const priorityTheme = value => ({ Urgent: 'red', High: 'amber' })[value] || 'gray'
function dismiss() {
  ++detailGeneration; selected.value = null; detailBusy.value = false
  history.value = { items: [] }; transcript.value = { items: [] }; deliveries.value = { items: [] }; feedback.value = ''
}
function select(row) {
  openRoute('#/tickets?ticket=' + encodeURIComponent(row.name), !!selected.value)
  show(row)
}
function show(row) {
  dismiss(); selected.value = row; owner.value = row.assigned_to || ''; error.value = ''
  detail(row.name)
}
function close() { closeRoute('#/tickets'); dismiss() }
function readRoute() {
  if (location.hash.split('?')[0] !== '#/tickets') return
  const name = new URLSearchParams(location.hash.split('?')[1] || '').get('ticket')
  if (!name) { if (selected.value) dismiss() }
  else if (name !== selected.value?.name) show(page.value.items.find(row => row.name === name) || { name })
}
async function more(method) {
  const target = method === 'ai_history' ? history : method === 'deliveries' ? deliveries : transcript
  const name = selected.value.name, request = ++detailGeneration
  detailBusy.value = true; error.value = ''
  try {
    const result = await coreApi('tickets.' + method, { name, ...target.value.next })
    if (request === detailGeneration && selected.value?.name === name)
      target.value = { items: [...target.value.items, ...result.items], next: result.next }
  } catch (e) {
    if (request === detailGeneration) { close(); error.value = e.message }
  } finally { if (request === detailGeneration) detailBusy.value = false }
}
async function update(method, values = {}) {
  const name = selected.value.name
  saving.value = true; error.value = ''; feedback.value = ''
  try {
    const result = await coreApi('tickets.' + method, { name, ...values }, true)
    if (selected.value?.name === name) {
      if (method === 'claim') selected.value = { ...selected.value, ...result }
      await load()
      if (selected.value?.name === name) feedback.value = method === 'claim' ? 'You took over. AI is stopped for this conversation.' : 'Ticket updated.'
    }
  } catch (e) { error.value = e.message }
  finally { saving.value = false }
}
const searchTickets = useDebouncedSearch(() => JSON.stringify(filters.value), () => load(), () => { ++generation; page.value = { items: [] }; listBusy.value = true })
onMounted(async () => { try { businessTypes.value = await coreApi('api.business_types') } catch (e) { error.value = e.message } })
onMounted(() => { load(); readRoute(); window.addEventListener('popstate', readRoute) })
onBeforeUnmount(() => window.removeEventListener('popstate', readRoute))
useRealtimeRefresh(['Relay Ticket'], ['tickets'], () => load())
const ticketSentinel = useLoadMore({ loading: busy, hasMore: () => page.value.next, error, load: () => load(page.value.next) })
const historySentinel = useLoadMore({ loading: busy, hasMore: () => history.value.next, error, load: () => more('ai_history') })
const deliverySentinel = useLoadMore({ loading: busy, hasMore: () => deliveries.value.next, error, load: () => more('deliveries') })
const transcriptSentinel = useLoadMore({ loading: busy, hasMore: () => transcript.value.next, error, load: () => more('transcript') })
</script>
<template>
  <section class="v1-screen"><div class="v1-content space-y-4">
    <WorkspaceHeading description="Review handoffs, assign an owner and follow each conversation." />
    <form class="automation-filter-bar" @submit.prevent="searchTickets">
      <div class="automation-chips" role="group" aria-label="Ticket status">
        <button v-for="value in ['', 'Open', 'In progress', 'Resolved', 'Closed']" :key="value" type="button" class="automation-chip" :aria-pressed="filters.status === value" :disabled="busy" @click="status(value)">{{ value || 'All tickets' }}</button>
      </div>
      <div class="automation-chips" role="group" aria-label="My tickets">
        <button v-for="option in [{ value: 'assigned', label: 'Assigned to me' }, { value: 'tagged', label: 'Tagged me' }]" :key="option.value" type="button" class="automation-chip" :aria-pressed="filters.mine === option.value" :disabled="busy" @click="mine(option.value)">{{ option.label }}</button>
      </div>
      <ChoiceField :model-value="filters.business_doctype" :field="{ label: 'Business type', options: businessTypes }" @update:model-value="value => { filters.business_doctype = value; filters.business_name = '' }" />
      <RemoteLinkField v-if="filters.business_doctype" :key="filters.business_doctype" v-model="filters.business_name" :field="{ label: 'Business record', method: 'api.business_records', params: { doctype: filters.business_doctype }, doctype: filters.business_doctype }" />
      <ChoiceField v-model="filters.assigned_to" :field="assigneeField" />
      <FormControl v-model="filters.category" label="Category" placeholder="Category" type="select" :options="['', 'Query', 'Payment evidence', 'Support', 'Other']" />

    </form>
    <ErrorMessage :message="error" />
    <div class="v1-detail-grid" :class="{ 'v1-detail-grid--browse': !selected }">
      <div class="space-y-3">
        <LoadingRows v-if="busy && !page.items.length" label="Loading tickets…" />
        <button v-for="row in page.items" :key="row.name" type="button" :aria-label="'Open ticket: ' + recordTitle(row, 'Ticket')" class="v1-list-card ticket-card" :aria-pressed="selected?.name === row.name" @click="select(row)">
          <div class="automation-card-heading"><strong>{{ recordTitle(row, 'Ticket') }}</strong><span class="flex gap-1"><Badge v-if="['High', 'Urgent'].includes(row.priority)" :label="row.priority" :theme="priorityTheme(row.priority)" /><Badge :label="row.status" :theme="row.status === 'Open' ? 'amber' : row.status === 'In progress' ? 'blue' : 'gray'" /></span></div>
          <div class="flex flex-wrap items-center gap-2"><Badge class="ticket-business-badge" :label="row.business_name ? linkedTitle(row.business_doctype, row.business_name) : 'Conversation'" /><span>{{ row.category }} · {{ linkedTitle('User', row.assigned_to, 'Unassigned') }} · {{ relativeTime(row.creation) }}</span></div>
        </button>
        <WorkspaceState v-if="!busy && !error && !page.items.length" title="No matching tickets" description="Try another status or clear the filters to see all tickets." icon="bookmark"><Button label="Clear filters" @click="reset" /></WorkspaceState>
        <div v-if="page.next" ref="ticketSentinel" class="h-px" aria-hidden="true" />
      </div>
      <article v-if="selected" class="workflow-card ticket-detail" :aria-busy="detailBusy">
        <div class="automation-card-heading"><Button class="mobile-only ticket-back" icon="chevron-left" variant="ghost" aria-label="Back to tickets" title="Back to tickets" @click="close" /><h2 class="font-semibold">{{ recordTitle(selected, 'Ticket') }}</h2><Button class="desktop-only" label="Dismiss" @click="close" /></div><div class="flex flex-wrap gap-2"><Badge :label="selected.status" theme="blue" /><Badge v-if="selected.priority" :label="selected.priority + ' priority'" :theme="priorityTheme(selected.priority)" /><span v-if="selected.assigned_to" class="text-sm">Assigned to {{ linkedTitle('User', selected.assigned_to) }}</span></div><p class="whitespace-pre-wrap">{{ selected.brief }}</p>
        <div v-if="aiEnabled && selected.conversation_key && selected.company" class="space-y-2">
          <div class="flex flex-wrap items-center gap-3">
            <Badge :label="selected.ai_disabled ? (staffTookOver ? 'Staff took over' : 'AI stopped') : 'AI active'" :theme="selected.ai_disabled ? 'gray' : 'green'" />
            <Button v-if="selected.can_take_over && !staffTookOver" label="Take over" :loading="saving" :disabled="busy" @click="update('claim')" />
          </div>
          <p v-if="staffTookOver">{{ linkedTitle('User', selected.ownership_actor, 'Staff') }} · {{ relativeTime(selected.ownership_at) }}</p>
          <p v-else-if="selected.ai_disabled">AI is stopped. Take over to handle this conversation.</p>
          <p v-else>Take over to stop AI for this conversation and reply yourself.</p>
        </div>
        <p role="status" aria-live="polite">{{ feedback }}</p>
        <LoadingRows v-if="detailBusy && !transcript.items.length" label="Loading conversation…" />
        <p class="ticket-business-name">{{ linkedTitle(selected.business_doctype, selected.business_name) }}</p><p v-if="selected.handoff_reason">{{ selected.handoff_reason }}</p>
        <div v-if="selected.linked_drafts?.length" class="space-y-2">
          <h3 class="font-semibold">Documents for review</h3>
          <a v-for="draft in selected.linked_drafts" :key="draft.doctype + ':' + draft.name" class="v1-link block"
            :href="'/app/' + encodeURIComponent(draft.doctype.toLowerCase().replaceAll(' ', '-')) + '/' + encodeURIComponent(draft.name)">
            {{ draft.doctype }} · {{ linkedTitle(draft.doctype, draft.name) }} · {{ ['Draft', 'Submitted', 'Cancelled'][draft.docstatus] }}
          </a>
          <p>Open each draft, check the details and submit when ready.</p>
        </div>
        <a v-for="message in selected.messages" :key="message.message" class="v1-link" :href="'#/messages?message=' + encodeURIComponent(message.message)">Open conversation · {{ linkedTitle('Relay Channel', message.channel, 'Conversation') }}</a>
        <section v-if="aiEnabled" aria-label="AI history" class="space-y-3">
          <h3 class="font-semibold">AI history</h3>
          <p v-if="!detailBusy && !history.items.length">No AI activity recorded.</p>
          <ol class="space-y-3">
            <li v-for="run in history.items" :key="run.name" class="ticket-history-entry space-y-2">
              <div class="flex flex-wrap items-center gap-2"><strong>{{ recordTitle(run.event, 'Triage · no matched event') }}</strong><Badge :label="run.status" /></div>
              <p>{{ relativeTime(run.creation) }}<span v-if="run.event_version"> · Event version {{ run.event_version }}</span></p>
              <div v-if="run.search">
                <p><strong>Search announcement:</strong> {{ run.search.purpose }} · {{ run.search.reference }}</p>
                <p>{{ run.search.confirmed ? 'Search confirmed' : 'Confirmation not recorded' }}</p>
              </div>
              <p>{{ run.read_count }} {{ run.read_count === 1 ? 'read' : 'reads' }} completed. Raw results are kept private.</p>
              <ol v-if="run.actions.length" class="space-y-2" aria-label="Ordered actions">
                <li v-for="action in run.actions" :key="action.name">
                  {{ action.step }}. {{ action.action === 'create_draft' ? 'Create draft' : action.action === 'reply' ? 'Reply' : action.action }} · {{ action.status }}
                  <span v-if="action.approval"> · Approval {{ action.approval.toLowerCase() }}</span>
                </li>
              </ol>
              <p v-for="delivery in run.deliveries" :key="delivery.name">Reply delivery · {{ delivery.status }}<span v-if="['Dispatching', 'Queued', 'Uncertain'].includes(delivery.status)">. Delivery is outstanding; a message already accepted by the provider may still arrive after takeover.</span></p>
            </li>
          </ol>
          <div v-if="history.next" ref="historySentinel" class="h-px" aria-hidden="true" />
        </section>
        <section aria-label="Episode deliveries" class="space-y-3">
          <h3 class="font-semibold">Deliveries and notices</h3>
          <p v-if="!detailBusy && !deliveries.items.length">No deliveries recorded.</p>
          <p v-for="delivery in deliveries.items" :key="delivery.name">
            {{ delivery.kind }} · {{ delivery.status }}
            <span v-if="['Dispatching', 'Queued', 'Uncertain'].includes(delivery.status)">. Delivery is outstanding; an accepted message may still arrive after takeover.</span>
            <span v-if="delivery.status === 'Suppressed'">. Automatic delivery stopped; staff review required.</span>
          </p>
          <div v-if="deliveries.next" ref="deliverySentinel" class="h-px" aria-hidden="true" />
        </section>
        <section aria-label="Episode transcript" class="space-y-3">
          <h3 class="font-semibold">Conversation</h3>
          <p v-if="!detailBusy && !transcript.items.length">No episode messages available.</p>
          <ol class="space-y-3">
            <li v-for="message in transcript.items" :key="message.name" class="ticket-history-entry">
              <p>{{ message.direction }} · {{ message.status }} · {{ relativeTime(message.sent_at || message.creation) }}</p>
              <p class="whitespace-pre-wrap">{{ message.content || 'Attachment or message content unavailable' }}</p>
              <a class="v1-link" :href="'#/messages?message=' + encodeURIComponent(message.name)">Open message</a>
            </li>
          </ol>
          <div v-if="transcript.next" ref="transcriptSentinel" class="h-px" aria-hidden="true" />
        </section>
        <TicketDiscussion v-if="selected.messages" :ticket="selected" @changed="load()" />
        <form v-if="selected.can_assign" class="space-y-3" @submit.prevent="update('assign', { user: owner })"><RemoteLinkField v-model="owner" :field="{ label: 'Assign to', method: 'collaboration.colleagues', params: { contact: selected.messages?.[0]?.contact }, placeholder: 'Search colleagues…', readOnly: busy || !selected.messages?.length, initialOptions: selected.assigned_to ? [{ value: selected.assigned_to, label: linkedTitle('User', selected.assigned_to) }] : [] }" /><Button type="submit" label="Assign" :disabled="busy" /></form>
        <div class="flex flex-wrap gap-3"><Button label="Start work" :disabled="busy || selected.status === 'In progress'" @click="update('update_status', { status: 'In progress' })" /><Button label="Close ticket" :disabled="busy || selected.status === 'Closed'" @click="update('update_status', { status: 'Closed' })" /><Button v-if="selected.can_resume" label="Resume AI" :disabled="busy" @click="update('resume_ai')" /><Button v-if="selected.can_release" label="Close and release" :disabled="busy" @click="update('close_and_release')" /></div>
      </article>
    </div>
  </div></section>
</template>

<style scoped>
.ticket-detail { min-width: 0; overflow-wrap: anywhere; }
.ticket-history-entry { border-top: 1px solid var(--outline-gray-2); padding-top: 0.75rem; }
</style>
