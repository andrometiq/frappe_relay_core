<script setup>
import { useLoadMore } from '../composables/useLoadMore'
import { useDebouncedSearch } from '../composables/useDebouncedSearch'
import { recordTitle } from '../services/recordTitle'
import { linkedTitle } from '../services/linkedTitle'
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Badge, Button, ErrorMessage, FeatherIcon, TextInput, toast } from '@relay/ui'
import TicketSettings from './TicketSettings.vue'
import RelaySelect from './RelaySelect.vue'
import TicketDashboard from './tickets/TicketDashboard.vue'
import TicketDialog from './tickets/TicketDialog.vue'
import { useTicketSettings } from '../composables/useTicketSettings'
import { emptyTicketFilters, pickerOptions, readTicketRoute, statusLook, ticketRoute } from '../services/ticketSettings'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import WorkspaceState from './WorkspaceState.vue'
import LoadingRows from './LoadingRows.vue'
import { dateTime } from './relativeTime'
import { closeRoute, openRoute } from '../useViewRoute'
const capabilities = inject('relayCapabilities', ref({}))
const aiEnabled = computed(() => Boolean(capabilities.value?.ai))
const { settings, load: loadSettings } = useTicketSettings()
const view = ref('dashboard')
const views = [{ value: 'dashboard', label: 'Dashboard' }, { value: 'tickets', label: 'Tickets' }]
const businessTypes = ref([])
const businessOptions = computed(() => [{ value: '', label: 'All business types' }, ...businessTypes.value.filter(row => row.enabled).map(row => ({ value: row.business_doctype, label: row.label || row.business_doctype }))])
const filters = ref(emptyTicketFilters())
const page = ref({ items: [] }), selected = ref(null), error = ref(''), saveError = ref('')
const listBusy = ref(false), detailBusy = ref(false), saving = ref(false)
const busy = computed(() => listBusy.value || detailBusy.value || saving.value)
const statusTabs = computed(() => pickerOptions(settings.value.statuses, 'All'))
const look = ticket => statusLook(settings.value, ticket)
const hasFilters = computed(() => Object.entries(filters.value).some(([key, value]) => ['assigned_to', 'ticket_type'].includes(key) || Boolean(value)))
// Dashboard filters that have no control of their own on the list.
const filterLabel = computed(() => {
  const { state, assigned, resolved_today, assigned_to, ticket_type, exclude_assignees, unlinked } = filters.value
  return [resolved_today && 'Resolved today', !resolved_today && state && state + ' tickets', assigned && 'With an owner',
    exclude_assignees && 'Other assignees', assigned_to === '' ? 'Unassigned' : assigned_to && 'Assigned to: ' + linkedTitle('User', assigned_to),
    ticket_type !== undefined && 'Type: ' + (ticket_type || 'No type'), unlinked && 'Not linked to a business record'].filter(Boolean).join(' · ')
})
const resetFilters = () => { filters.value = emptyTicketFilters() }
const listRoute = () => ticketRoute({ view: view.value, filters: filters.value })
watch(listRoute, route => { if (location.hash.startsWith('#/tickets') && !selected.value) openRoute(route, true) })
let generation = 0, detailGeneration = 0
async function detail(name) {
  const request = ++detailGeneration; detailBusy.value = true
  try {
    const ticket = await coreApi('tickets.read', { name })
    if (request === detailGeneration && selected.value?.name === name) selected.value = ticket
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
const setFilter = values => { filters.value = { ...filters.value, ...values } }
function pickStatus(ticket_status) {
  const { state, resolved_today, ...rest } = filters.value
  filters.value = { ...rest, ticket_status }
}
function dismiss() { ++detailGeneration; selected.value = null; detailBusy.value = false; saveError.value = '' }
function select(row) {
  openRoute(ticketRoute({ view: view.value, filters: filters.value, ticket: row.name }), !!selected.value)
  show(row)
}
function show(row) {
  dismiss(); selected.value = row; error.value = ''
  detail(row.name)
}
function close() { closeRoute(listRoute()); dismiss() }
function readRoute() {
  if (location.hash.split('?')[0] !== '#/tickets') return
  const route = readTicketRoute(location.hash)
  view.value = route.view
  if (JSON.stringify(route.filters) !== JSON.stringify(filters.value)) filters.value = route.filters
  const name = route.ticket
  if (!name) { if (selected.value) dismiss() }
  else if (name !== selected.value?.name) show(page.value.items.find(row => row.name === name) || { name })
}
const updated = {
  claim: () => 'You took over. AI is stopped for this conversation.',
  resume_ai: () => 'AI resumed',
  close_and_release: () => 'Ticket closed',
  update_status: values => 'Status changed to ' + (settings.value.statuses.find(row => row.name === values.status)?.label || values.status),
  assign: values => values.user ? 'Assigned to ' + linkedTitle('User', values.user) : 'Owner removed',
}
async function update(method, values = {}) {
  const name = selected.value.name
  saving.value = true; saveError.value = ''
  try {
    await coreApi('tickets.' + method, { name, ...values }, true)
    if (selected.value?.name === name) await load()
    toast(updated[method](values))
  } catch (e) {
    if (selected.value?.name === name) saveError.value = e.message
    else error.value = e.message
  } finally { saving.value = false }
}
useDebouncedSearch(() => JSON.stringify(filters.value), () => load(), () => { ++generation; page.value = { items: [] }; listBusy.value = true })
onMounted(() => {
  loadSettings().catch(e => { error.value = e.message })
  coreApi('business_types.list_types').then(rows => { businessTypes.value = rows }, e => { error.value = e.message })
})
onMounted(() => { load(); readRoute(); window.addEventListener('popstate', readRoute); window.addEventListener('hashchange', readRoute) })
onBeforeUnmount(() => { window.removeEventListener('popstate', readRoute); window.removeEventListener('hashchange', readRoute) })
useRealtimeRefresh(['Relay Ticket'], ['tickets'], load)
const ticketSentinel = useLoadMore({ loading: busy, hasMore: () => page.value.next, error, load: () => load(page.value.next) })
</script>
<template>
  <section class="v1-screen"><div class="v1-content space-y-4">
    <template v-if="view === 'settings' && settings.can_manage">
      <div class="ticket-page-head"><Button variant="outline" icon-left="chevron-left" label="Back to tickets" @click="view = 'tickets'" /><h2>Ticket settings</h2></div>
      <TicketSettings />
    </template>
    <template v-else>
      <div class="ticket-page-head">
        <div class="ticket-tabs" role="tablist" aria-label="Tickets view">
          <button v-for="option in views" :key="option.value" type="button" role="tab" :aria-selected="view === option.value" @click="view = option.value">{{ option.label }}</button>
        </div>
        <Button v-if="settings.can_manage" variant="outline" icon-left="settings" label="Ticket settings" aria-label="Ticket settings" class="ticket-page-head__settings" @click="view = 'settings'" />
      </div>
      <ErrorMessage :message="error" />
      <TicketDashboard v-if="view === 'dashboard'" :settings="settings" @open="select" />
      <template v-else>
        <div class="ticket-toolbar">
          <TextInput v-model="filters.query" class="ticket-toolbar__search" type="search" placeholder="Search tickets" aria-label="Search tickets" maxlength="80"><template #prefix><FeatherIcon name="search" /></template></TextInput>
          <RelaySelect v-model="filters.business_type" label="Business type" :options="businessOptions" />
          <button type="button" class="ticket-chip" :aria-pressed="!!filters.mine" @click="setFilter({ mine: filters.mine ? 0 : 1 })"><FeatherIcon name="user" :size="14" />Assigned to me</button>
        </div>
        <div class="ticket-status-tabs" role="tablist" aria-label="Ticket status">
          <button v-for="option in statusTabs" :key="option.value" type="button" role="tab" :aria-selected="filters.ticket_status === option.value" @click="pickStatus(option.value)">{{ option.label }}</button>
        </div>
        <div v-if="filterLabel" class="ticket-toolbar ticket-toolbar--filter">
          <span>{{ filterLabel }}</span>
          <Button label="Clear filter" variant="ghost" @click="resetFilters" />
        </div>
        <LoadingRows v-if="busy && !page.items.length" label="Loading tickets…" />
        <div v-if="page.items.length" class="ticket-table-wrap">
          <table class="ticket-table">
            <thead><tr><th>Ticket</th><th>Business type</th><th>Business record</th><th v-for="field in page.group_fields" :key="field.fieldname">{{ field.label }}</th><th>Assigned to</th><th>Status</th></tr></thead>
            <tbody><tr v-for="row in page.items" :key="row.name">
              <td data-label="Ticket"><button type="button" class="ticket-title" @click="select(row)"><strong>{{ recordTitle(row, 'Ticket') }}</strong><small>{{ row.name }} · {{ dateTime(row.creation) }}</small></button></td>
              <td data-label="Business type">{{ row.business_doctype || 'Not linked' }}</td>
              <td data-label="Business record">{{ row.business_title || '—' }}</td>
              <td v-for="field in page.group_fields" :key="field.fieldname" :data-label="field.label">{{ row.group_values?.[field.fieldname] || 'Not set' }}</td>
              <td data-label="Assigned to">{{ linkedTitle('User', row.assigned_to, 'Unassigned') }}</td>
              <td data-label="Status"><Badge :label="look(row).label" :theme="look(row).theme" /></td>
            </tr></tbody>
          </table>
        </div>
        <WorkspaceState v-if="!busy && !error && !page.items.length" class="ticket-empty" title="No tickets here" :description="hasFilters ? 'Try clearing the search and filters.' : 'Tickets will appear here when they are created.'" icon="bookmark"><Button v-if="hasFilters" label="Clear all filters" variant="outline" @click="resetFilters" /></WorkspaceState>
        <div v-if="page.next" ref="ticketSentinel" class="h-px" aria-hidden="true" />
      </template>
    </template>
    <TicketDialog v-if="selected" :ticket="selected" :settings="settings" :error="saveError" :busy="busy" :ai-enabled="aiEnabled" @update="update" @close="close" />
  </div></section>
</template>

<style scoped>
.ticket-page-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.ticket-page-head h2 { font-size: 15px; font-weight: 600; }
.ticket-page-head__settings { margin-left: auto; }
.ticket-tabs, .ticket-status-tabs { display: inline-flex; max-width: 100%; overflow-x: auto; scrollbar-width: none; padding: 2px; border-radius: 8px; background: var(--surface-gray-2); }
.ticket-tabs button, .ticket-status-tabs button { flex: none; height: 30px; padding: 0 14px; border-radius: 6px; font-size: 13px; color: var(--ink-gray-6); white-space: nowrap; }
.ticket-tabs button[aria-selected=true], .ticket-status-tabs button[aria-selected=true] { background: var(--surface-white); color: var(--ink-gray-9); font-weight: 600; box-shadow: 0 1px 2px rgb(0 0 0 / 12%); }
.ticket-status-tabs { display: flex; width: fit-content; }
.ticket-toolbar { display: flex; flex-wrap: wrap; align-items: end; gap: 8px; }
.ticket-toolbar--filter { align-items: center; font-size: 13px; color: var(--ink-gray-7); }
.ticket-toolbar__search { flex: 1 1 220px; min-width: 0; max-width: 360px; }
.ticket-chip { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 12px; border: 1px solid var(--outline-gray-2); border-radius: 999px; background: var(--surface-white); font-size: 13px; color: var(--ink-gray-7); white-space: nowrap; }
.ticket-chip[aria-pressed=true] { border-color: var(--outline-blue-1, var(--relay-accent)); background: var(--surface-blue-1, var(--relay-accent-soft)); color: var(--ink-blue-3); font-weight: 600; }
.ticket-table-wrap { overflow:auto; border:1px solid var(--outline-gray-2); border-radius:10px; }
.ticket-table { width:100%; border-collapse:collapse; font-size:13px; background:var(--surface-white); }
.ticket-table th, .ticket-table td { padding:10px 12px; text-align:left; border-bottom:1px solid var(--outline-gray-2); overflow-wrap:anywhere; }
.ticket-table th { font-size:12px; font-weight:600; color:var(--ink-gray-6); background:var(--surface-gray-1); }
.ticket-table th:first-child { width:38%; }
.ticket-table th:not(:first-child), .ticket-table td:not(:first-child) { min-width:110px; overflow-wrap:normal; }
.ticket-title { display:flex; flex-direction:column; justify-content:center; gap:4px; min-height:44px; min-width:140px; text-align:left; color:var(--ink-gray-9); }
.ticket-title small { color:var(--ink-gray-6); font-size:12px; }
.ticket-title:focus-visible { outline:2px solid var(--relay-accent); outline-offset:2px; }
.ticket-empty { min-height: min(50vh, 360px); }
@media (max-width: 768px) {
  .ticket-page-head__settings :deep(.relay-button__label) { display: none; }
  .ticket-toolbar--filter { align-items: center; font-size: 13px; color: var(--ink-gray-7); }
.ticket-toolbar__search { flex-basis: 100%; max-width: none; }
  .ticket-toolbar :deep(:is(input,select)) { min-height:44px !important; }
  .ticket-table, .ticket-table tbody { display:block; }
  .ticket-table thead { display:none; }
  .ticket-table tr { display:block; padding:12px; border-bottom:1px solid var(--outline-gray-2); }
  .ticket-table td { display:grid; grid-template-columns:minmax(90px, 35%) minmax(0,1fr); gap:12px; padding:6px 0; border:0; }
  .ticket-table td::before { content:attr(data-label); color:var(--ink-gray-6); font-size:12px; }
  .ticket-title { min-width:0; }
  .ticket-tabs button, .ticket-status-tabs button, .ticket-chip { min-height:44px; }
}
</style>
