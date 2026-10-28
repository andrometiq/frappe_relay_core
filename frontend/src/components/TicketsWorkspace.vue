<script setup>
import { useLoadMore } from '../composables/useLoadMore'
import ChoiceField from './fields/ChoiceField.vue'
import { useDebouncedSearch } from '../composables/useDebouncedSearch'
import { recordTitle } from '../services/recordTitle'
import { referenceName } from '../services/automationEditor'
import { linkedTitle } from '../services/linkedTitle'
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { Badge, Button, ErrorMessage, toast } from '@relay/ui'
import TicketSettings from './TicketSettings.vue'
import TicketFilters from './tickets/TicketFilters.vue'
import { useTicketSettings } from '../composables/useTicketSettings'
import { emptyTicketFilters, pickerOptions, statusLook } from '../services/ticketSettings'
import { distinctPeople } from '../services/ticketForm'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import TicketDiscussion from './TicketDiscussion.vue'
import WorkspaceState from './WorkspaceState.vue'
import LoadingRows from './LoadingRows.vue'
import { relativeTime } from './relativeTime'
import { closeRoute, openRoute } from '../useViewRoute'
const capabilities = inject('relayCapabilities', ref({}))
const aiEnabled = computed(() => Boolean(capabilities.value?.ai))
const businessTypes = ref([])
const { settings, load: loadSettings } = useTicketSettings()
const tab = ref('tickets')
const filters = ref(emptyTicketFilters())
const page = ref({ items: [] }), selected = ref(null), changingOwner = ref(false), error = ref('')
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
const statusOptions = computed(() => pickerOptions(settings.value.statuses, '', 'All'))
const categoryOptions = computed(() => pickerOptions(settings.value.categories, '', 'Any'))
const typeOptions = computed(() => pickerOptions(settings.value.types, '', 'Any'))
function reset() { filters.value = emptyTicketFilters() }
const detailStatusOptions = computed(() => pickerOptions(settings.value.statuses, selected.value?.ticket_status || '')
  .map(option => ({ ...option, theme: statusLook(settings.value, { ticket_status: option.value }).theme })))
const ownerField = computed(() => ({ label: 'New owner', placeholder: 'Search colleagues…', readOnly: busy.value,
  search: async (query, signal) => distinctPeople(await coreApi('collaboration.colleagues', { contact: selected.value.messages[0].contact, query }, false, { signal })) }))
const facts = computed(() => [
  ['Customer', selected.value.business_name ? linkedTitle(selected.value.business_doctype, selected.value.business_name) : ''],
  ['Category', [selected.value.category, selected.value.ticket_type].filter(Boolean).join(' · ')],
  ['Created', selected.value.creation ? relativeTime(selected.value.creation) : ''],
].filter(([, value]) => value))
const shownText = (text, ...others) => text && !others.includes(text) ? text : ''
const look = ticket => statusLook(settings.value, ticket)
const priorityTheme = value => ({ Urgent: 'red', High: 'amber' })[value] || 'gray'
function dismiss() {
  ++detailGeneration; selected.value = null; detailBusy.value = false
  history.value = { items: [] }; transcript.value = { items: [] }; deliveries.value = { items: [] }; changingOwner.value = false
}
function select(row) {
  openRoute('#/tickets?ticket=' + encodeURIComponent(row.name), !!selected.value)
  show(row)
}
function show(row) {
  dismiss(); selected.value = row; error.value = ''
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
const updated = {
  claim: () => 'You took over. AI is stopped for this conversation.',
  update_status: values => 'Status changed to ' + (detailStatusOptions.value.find(option => option.value === values.status)?.label || values.status),
  assign: values => values.user ? 'Assigned to ' + linkedTitle('User', values.user) : 'Owner removed',
}
async function update(method, values = {}) {
  const name = selected.value.name
  saving.value = true; error.value = ''
  try {
    const result = await coreApi('tickets.' + method, { name, ...values }, true)
    if (selected.value?.name === name) {
      if (method === 'claim') selected.value = { ...selected.value, ...result }
      changingOwner.value = false
      await load()
    }
    toast(updated[method]?.(values) || 'Saved')
  } catch (e) { error.value = e.message }
  finally { saving.value = false }
}
useDebouncedSearch(() => JSON.stringify(filters.value), () => load(), () => { ++generation; page.value = { items: [] }; listBusy.value = true })
onMounted(() => { loadSettings().catch(e => { error.value = e.message }) })
onMounted(async () => { try { businessTypes.value = await coreApi('api.business_types') } catch (e) { error.value = e.message } })
onMounted(() => { load(); readRoute(); window.addEventListener('popstate', readRoute) })
onBeforeUnmount(() => window.removeEventListener('popstate', readRoute))
useRealtimeRefresh(['Relay Ticket'], ['tickets'], load)
const ticketSentinel = useLoadMore({ loading: busy, hasMore: () => page.value.next, error, load: () => load(page.value.next) })
const historySentinel = useLoadMore({ loading: busy, hasMore: () => history.value.next, error, load: () => more('ai_history') })
const deliverySentinel = useLoadMore({ loading: busy, hasMore: () => deliveries.value.next, error, load: () => more('deliveries') })
const transcriptSentinel = useLoadMore({ loading: busy, hasMore: () => transcript.value.next, error, load: () => more('transcript') })
</script>
<template>
  <section class="v1-screen"><div class="v1-content space-y-4">
    <template v-if="tab === 'settings' && settings.can_manage">
      <div class="ticket-page-head"><Button variant="outline" icon-left="chevron-left" label="Back to tickets" @click="tab = 'tickets'" /><h2>Categories and statuses</h2></div>
      <TicketSettings />
    </template>
    <template v-else>
    <div class="ticket-page-head">
      <TicketFilters v-model="filters" class="ticket-page-head__filters" :status-options="statusOptions" :category-options="categoryOptions" :type-options="typeOptions" :business-types="businessTypes" :busy="busy">
        <Button v-if="settings.can_manage" variant="outline" icon-left="settings" label="Categories and statuses" aria-label="Categories and statuses" title="Categories and statuses" class="ticket-page-head__settings" @click="tab = 'settings'" />
      </TicketFilters>
    </div>
    <ErrorMessage :message="error" />
    <div class="v1-detail-grid" :class="{ 'v1-detail-grid--browse': !selected }">
      <div class="space-y-3">
        <LoadingRows v-if="busy && !page.items.length" label="Loading tickets…" />
        <button v-for="row in page.items" :key="row.name" type="button" :aria-label="'Open ticket: ' + recordTitle(row, 'Ticket')" :title="recordTitle(row, 'Ticket')" class="v1-list-card ticket-card" :aria-pressed="selected?.name === row.name" @click="select(row)">
          <div class="automation-card-heading"><strong>{{ row.business_name ? linkedTitle(row.business_doctype, row.business_name) : recordTitle(row, 'Ticket') }}</strong><span class="flex gap-1"><Badge v-if="['High', 'Urgent'].includes(row.priority)" :label="row.priority" :theme="priorityTheme(row.priority)" /><Badge :label="look(row).label" :theme="look(row).theme" /></span></div>
          <span v-if="row.business_name" class="ticket-card__subject">{{ recordTitle(row, 'Ticket') }}</span>
          <span class="ticket-card__meta">{{ row.category }} · <span :class="{ 'ticket-unassigned': !row.assigned_to }">{{ linkedTitle('User', row.assigned_to, 'Unassigned') }}</span> · {{ row.name }} · {{ relativeTime(row.creation) }}</span>
        </button>
        <WorkspaceState v-if="!busy && !error && !page.items.length" class="ticket-empty" title="No matching tickets" description="Try another status or clear the filters to see all tickets." icon="bookmark"><Button variant="outline" label="Clear filters" @click="reset" /></WorkspaceState>
        <div v-if="page.next" ref="ticketSentinel" class="h-px" aria-hidden="true" />
      </div>
      <article v-if="selected" class="workflow-card ticket-detail" :aria-busy="detailBusy">
        <header class="ticket-detail__head"><Button class="mobile-only" icon="chevron-left" variant="ghost" aria-label="Back to tickets" title="Back to tickets" @click="close" /><div class="ticket-detail__title"><small>{{ selected.name }}</small><h2>{{ recordTitle(selected, 'Ticket') }}</h2></div><Button class="desktop-only" icon="x" variant="ghost" aria-label="Close" title="Close" @click="close" /></header>
        <div class="ticket-detail__fields">
          <span class="ticket-detail__label">Status</span>
          <div v-if="selected.can_edit" class="ticket-status-switch" role="radiogroup" aria-label="Status">
            <button v-for="option in detailStatusOptions" :key="option.value" type="button" role="radio" :class="'ticket-status--' + option.theme" :aria-checked="selected.ticket_status === option.value" :disabled="busy" @click="option.value !== selected.ticket_status && update('update_status', { status: option.value })"><span aria-hidden="true" />{{ option.label }}</button>
          </div>
          <span v-else><Badge :label="look(selected).label" :theme="look(selected).theme" /></span>
          <span class="ticket-detail__label">Owner</span>
          <div class="ticket-owner">
            <strong :class="{ 'ticket-unassigned': !selected.assigned_to }">{{ linkedTitle('User', selected.assigned_to, 'Unassigned') }}</strong>
            <Button v-if="selected.can_assign && selected.messages?.length && !changingOwner" variant="outline" size="xs" :label="selected.assigned_to ? 'Change owner' : 'Assign'" :disabled="busy" @click="changingOwner = true" />
            <div v-if="changingOwner" class="ticket-owner__picker">
              <ChoiceField :model-value="''" :field="ownerField" @update:model-value="user => user && update('assign', { user })" />
              <div class="flex gap-2"><Button v-if="selected.assigned_to" variant="outline" label="Remove owner" :disabled="busy" @click="update('assign', { user: '' })" /><Button variant="outline" label="Cancel" @click="changingOwner = false" /></div>
            </div>
          </div>
          <template v-if="selected.priority"><span class="ticket-detail__label">Priority</span><span><Badge :label="selected.priority" :theme="priorityTheme(selected.priority)" /></span></template>
          <template v-for="[label, value] in facts" :key="label"><span class="ticket-detail__label">{{ label }}</span><span>{{ value }}</span></template>
        </div>
        <p v-if="shownText(selected.brief, recordTitle(selected, 'Ticket'))" class="whitespace-pre-wrap">{{ selected.brief }}</p>
        <p v-if="shownText(selected.handoff_reason, selected.brief, recordTitle(selected, 'Ticket'))">{{ selected.handoff_reason }}</p>
        <div v-if="aiEnabled && selected.conversation_key && selected.company" class="space-y-2">
          <div class="flex flex-wrap items-center gap-3">
            <Badge :label="selected.ai_disabled ? (staffTookOver ? 'Staff took over' : 'AI stopped') : 'AI active'" :theme="selected.ai_disabled ? 'gray' : 'green'" />
            <Button v-if="selected.can_take_over && !staffTookOver" variant="outline" label="Take over" :loading="saving" :disabled="busy" @click="update('claim')" />
            <Button v-if="selected.can_resume" variant="outline" label="Resume AI" :disabled="busy" @click="update('resume_ai')" />
            <Button v-if="selected.can_release" variant="outline" label="Close and release" :disabled="busy" @click="update('close_and_release')" />
          </div>
          <p v-if="staffTookOver">{{ linkedTitle('User', selected.ownership_actor, 'Staff') }} · {{ relativeTime(selected.ownership_at) }}</p>
          <p v-else-if="selected.ai_disabled">AI is stopped. Take over to handle this conversation.</p>
          <p v-else>Take over to stop AI for this conversation and reply yourself.</p>
        </div>
        <LoadingRows v-if="detailBusy && !transcript.items.length" label="Loading conversation…" />
        <div v-if="selected.linked_drafts?.length" class="space-y-2">
          <h3 class="font-semibold">Documents for review</h3>
          <a v-for="draft in selected.linked_drafts" :key="draft.doctype + ':' + draft.name" class="v1-link block"
            :href="'/app/' + encodeURIComponent(draft.doctype.toLowerCase().replaceAll(' ', '-')) + '/' + encodeURIComponent(draft.name)">
            {{ draft.doctype }} · {{ linkedTitle(draft.doctype, draft.name) }} · {{ ['Draft', 'Submitted', 'Cancelled'][draft.docstatus] }}
          </a>
          <p>Open each draft, check the details and submit when ready.</p>
        </div>
        <a v-for="message in selected.messages" :key="message.message" class="v1-link" :href="'#/messages?message=' + encodeURIComponent(message.message)">Open chat · {{ linkedTitle('Relay Channel', message.channel, 'Conversation') }}</a>
        <section v-if="aiEnabled" aria-label="AI history" class="space-y-3">
          <h3 class="font-semibold">AI history</h3>
          <p v-if="!detailBusy && !history.items.length">No AI activity recorded.</p>
          <ol class="space-y-3">
            <li v-for="run in history.items" :key="run.name" class="ticket-history-entry space-y-2">
              <div class="flex flex-wrap items-center gap-2"><strong>{{ recordTitle(run.event, 'Triage · no matched event') }}</strong><Badge :label="run.status" /></div>
              <p>{{ relativeTime(run.creation) }}<span v-if="run.event_version"> · Event version {{ run.event_version }}</span></p>
              <div v-if="run.search">
                <p><strong>Search announcement:</strong> {{ run.search.purpose }} · {{ referenceName(run.search.reference) }}</p>
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
        <section v-if="deliveries.items.length" aria-label="Messages sent about this ticket" class="space-y-3">
          <h3 class="font-semibold">Messages sent about this ticket</h3>
          <p v-for="delivery in deliveries.items" :key="delivery.name">
            {{ delivery.kind }} · {{ delivery.status }}
            <span v-if="['Dispatching', 'Queued', 'Uncertain'].includes(delivery.status)">. Delivery is outstanding; an accepted message may still arrive after takeover.</span>
            <span v-if="delivery.status === 'Suppressed'">. Automatic delivery stopped; staff review required.</span>
          </p>
          <div v-if="deliveries.next" ref="deliverySentinel" class="h-px" aria-hidden="true" />
        </section>
        <section aria-label="Episode transcript" class="space-y-3">
          <h3 class="font-semibold">Conversation</h3>
          <p v-if="!detailBusy && !transcript.items.length">No messages in this conversation yet.</p>
          <ol class="space-y-3">
            <li v-for="message in transcript.items" :key="message.name" class="ticket-history-entry">
              <p>{{ message.direction }}<template v-if="message.direction === 'Outgoing' && message.status"> · {{ message.status }}</template> · {{ relativeTime(message.sent_at || message.creation) }}</p>
              <p class="whitespace-pre-wrap">{{ message.content || 'Attachment or message content unavailable' }}</p>
              <a class="v1-link" :href="'#/messages?message=' + encodeURIComponent(message.name)">Open message</a>
            </li>
          </ol>
          <div v-if="transcript.next" ref="transcriptSentinel" class="h-px" aria-hidden="true" />
        </section>
        <TicketDiscussion v-if="selected.messages" :ticket="selected" @changed="load()" />
      </article>
    </div>
    </template>
  </div></section>
</template>

<style scoped>
.ticket-page-head { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 8px; }
.ticket-page-head h2 { align-self: center; font-size: 15px; font-weight: 600; }
.ticket-page-head__filters { flex: 1 1 auto; min-width: 0; }
.ticket-page-head__settings { flex: none; margin-left: auto; }
.ticket-empty { grid-column: 1 / -1; min-height: min(60vh, 440px); }
.ticket-card__subject { display: block; font-size: 13px; color: var(--ink-gray-8); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ticket-card__meta { display: block; font-size: 12.5px; color: var(--ink-gray-6); }
.ticket-unassigned { color: var(--relay-amber, #b86e00); }
.ticket-detail { min-width: 0; overflow-wrap: anywhere; }
.ticket-detail__head { display: flex; align-items: center; gap: 8px; }
.ticket-detail__title { flex: 1; min-width: 0; }
.ticket-detail__title small { display: block; font-size: 12px; color: var(--ink-gray-5); }
.ticket-detail__head h2 { font-size: 16px; font-weight: 600; }
.ticket-detail__fields { display: grid; grid-template-columns: 80px minmax(0, 1fr); align-items: center; gap: 10px 12px; font-size: 13px; }
.ticket-detail__label { color: var(--ink-gray-5); font-size: 12.5px; }
.ticket-status-switch { display: inline-flex; flex-wrap: wrap; gap: 4px; padding: 2px; border-radius: 8px; background: var(--surface-gray-2); justify-self: start; max-width: 100%; }
.ticket-status-switch button { display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 10px; border-radius: 6px; font-size: 13px; color: var(--ink-gray-6); white-space: nowrap; }
.ticket-status-switch button > span { flex: none; width: 8px; height: 8px; border-radius: 999px; background: var(--ink-gray-4); }
.ticket-status-switch button[aria-checked=true] { background: var(--surface-white); color: var(--ink-gray-9); font-weight: 600; box-shadow: 0 1px 2px rgb(0 0 0 / 12%); }
.ticket-status--blue > span { background: var(--relay-accent, #0f6cbd) !important; }
.ticket-status--green > span { background: var(--relay-green, #107c10) !important; }
.ticket-status--amber > span { background: var(--relay-amber, #b86e00) !important; }
.ticket-status--red > span { background: var(--relay-red, #c42b1c) !important; }
.ticket-owner { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.ticket-owner__picker { display: grid; gap: 8px; flex-basis: 100%; }
.ticket-history-entry { border-top: 1px solid var(--outline-gray-2); padding-top: 0.75rem; }
@media (max-width: 768px) {
  .ticket-page-head__settings :deep(.relay-button__label) { display: none; }
  .ticket-detail__fields { grid-template-columns: 1fr; gap: 4px; }
  .ticket-detail__fields > :not(.ticket-detail__label) { margin-bottom: 8px; }
  .ticket-status-switch { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; }
  :global(.v1-screen:has(.ticket-detail) .ticket-page-head) { display: none; }
}
</style>
