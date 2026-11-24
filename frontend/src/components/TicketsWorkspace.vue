<script setup>
import { useLoadMore } from '../composables/useLoadMore'
import { useDebouncedSearch } from '../composables/useDebouncedSearch'
import { recordTitle } from '../services/recordTitle'
import { linkedTitle } from '../services/linkedTitle'
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Badge, Button, ErrorMessage, FeatherIcon, TextInput, toast } from '@relay/ui'
import UserAvatar from './UserAvatar.vue'
import TicketSettings from './TicketSettings.vue'
import PageSidebar from './shell/PageSidebar.vue'
import TicketDashboard from './tickets/TicketDashboard.vue'
import TicketDialog from './tickets/TicketDialog.vue'
import NewTicketDialog from './tickets/NewTicketDialog.vue'
import { useTicketSettings } from '../composables/useTicketSettings'
import { emptyTicketFilters, pickerOptions, readTicketRoute, statusLook, ticketRoute, ticketViewFilters, ticketViewKey, ticketViews } from '../services/ticketSettings'
import { coreApi } from '../services/coreApi'
import { businessTypeOptions } from '../services/ticketForm'
import { useRealtimeRefresh } from '../composables/useRealtimeRefresh'
import LoadingRows from './LoadingRows.vue'
import { dateTime, listTime, relativeTime } from './relativeTime'
import { closeRoute, openRoute } from '../useViewRoute'
const capabilities = inject('relayCapabilities', ref({}))
const aiEnabled = computed(() => Boolean(capabilities.value?.ai))
const me = window.frappe?.session?.user || ''
const { settings, load: loadSettings } = useTicketSettings()
const view = ref('tickets')
const businessTypes = ref([])
const typeOptions = computed(() => businessTypeOptions(businessTypes.value))
const filters = ref(emptyTicketFilters())
const typeLabel = doctype => typeOptions.value.find(row => row.value === doctype)?.label || doctype
const page = ref({ items: [] }), selected = ref(null), error = ref(''), saveError = ref(''), creating = ref(false)
const listBusy = ref(false), detailBusy = ref(false), saving = ref(false)
const busy = computed(() => listBusy.value || detailBusy.value || saving.value)
const statusOptions = computed(() => pickerOptions(settings.value.statuses, 'All statuses'))
const look = ticket => statusLook(settings.value, ticket)
const hasFilters = computed(() => Object.entries(filters.value).some(([key, value]) => ['assigned_to', 'ticket_type'].includes(key) || Boolean(value)))
// The dashboard numbers count the sidebar views and the stat cards; they refresh with ticket events.
const counts = ref(null)
const sections = computed(() => ticketViews(counts.value, settings.value, me, typeOptions.value))
const activeView = computed(() => ticketViewKey(sections.value, filters.value))
const activeItem = computed(() => sections.value.flatMap(section => section.items).find(item => item.key === activeView.value))
const heading = computed(() => activeItem.value ? (activeItem.value.key.startsWith('type:') ? 'Open · ' + activeItem.value.label : activeItem.value.label) : 'Filtered tickets')
const stats = computed(() => {
  const totals = counts.value?.totals
  if (!totals) return []
  const oldest = counts.value.oldest_open
  return [
    { label: 'Open', value: totals.open, hint: totals.assigned + ' with an owner', filters: { state: 'Open' } },
    { label: 'Unassigned', value: totals.unassigned, hint: 'Needs an owner', filters: { state: 'Open', assigned_to: '' } },
    { label: 'Resolved today', value: totals.resolved_today, hint: 'Closed since midnight', filters: { resolved_today: 1 } },
    { label: 'Oldest open', value: oldest ? relativeTime(oldest.creation).replace(' ago', '') : '—', hint: oldest ? recordTitle(oldest, 'Ticket') : 'No open tickets', ticket: oldest },
  ]
})
// Dashboard filters that have no control of their own on the list.
const filterLabel = computed(() => {
  if (activeView.value) return ''
  const { state, assigned, resolved_today, assigned_to, ticket_type, exclude_assignees, unlinked, mine, business_type } = filters.value
  return [resolved_today && 'Resolved today', !resolved_today && state && state + ' tickets', Number(mine) && 'Assigned to me',
    business_type && 'Business type: ' + typeLabel(business_type), assigned && 'With an owner',
    exclude_assignees && 'Other assignees', assigned_to === '' ? 'Unassigned' : assigned_to && 'Assigned to: ' + linkedTitle('User', assigned_to),
    ticket_type !== undefined && 'Type: ' + (ticket_type || 'No type'), unlinked && 'Not linked to a business record'].filter(Boolean).join(' · ')
})
const resetFilters = () => { filters.value = emptyTicketFilters() }
const listRoute = () => ticketRoute({ view: view.value, filters: filters.value })
watch(listRoute, route => { if (location.hash.startsWith('#/tickets') && !selected.value) openRoute(route, true) })
let generation = 0, detailGeneration = 0, countGeneration = 0
async function loadCounts() {
  const request = ++countGeneration
  try { const result = await coreApi('tickets.dashboard'); if (request === countGeneration) counts.value = result }
  catch (e) { if (request === countGeneration) error.value = e.message }
}
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
function pickView(item) {
  view.value = 'tickets'
  filters.value = ticketViewFilters(item, filters.value)
}
function openStat(stat) {
  if (stat.ticket) select(stat.ticket)
  else if (stat.filters) { view.value = 'tickets'; filters.value = { ...emptyTicketFilters(), ...stat.filters } }
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
function created(ticket) {
  toast('Ticket ' + ticket.name + ' created')
  loadCounts(); load(); select(ticket)
}
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
  loadCounts()
})
onMounted(() => { load(); readRoute(); window.addEventListener('popstate', readRoute); window.addEventListener('hashchange', readRoute) })
onBeforeUnmount(() => { window.removeEventListener('popstate', readRoute); window.removeEventListener('hashchange', readRoute) })
// One coalesced refresh per burst of ticket events: the counts always, the list only while it shows.
let listStale = false
function refreshView() {
  listStale = view.value !== 'tickets'
  return listStale ? loadCounts() : Promise.all([load(), loadCounts()])
}
watch(view, value => { if (value === 'tickets' && listStale) { listStale = false; load() } })
useRealtimeRefresh(['Relay Ticket'], ['tickets'], refreshView)
const ticketSentinel = useLoadMore({ loading: busy, hasMore: () => page.value.next, error, load: () => load(page.value.next) })
</script>
<template>
  <div class="relay-page ticket-page">
    <PageSidebar title="Tickets" label="Ticket views" :sections="sections" :active="view === 'tickets' ? activeView : ''" @select="pickView" />
    <main class="page-main" aria-label="Tickets">
      <template v-if="view === 'settings' && settings.can_manage">
        <header class="page-head"><Button variant="ghost" icon="chevron-left" aria-label="Back to tickets" @click="view = 'tickets'" /><h2>Ticket statuses and types</h2></header>
        <div class="settings-page"><TicketSettings /></div>
      </template>
      <template v-else-if="view === 'dashboard'">
        <header class="page-head">
          <Button variant="ghost" icon="chevron-left" aria-label="Back to tickets" @click="view = 'tickets'" /><h2>Ticket dashboard</h2>
        </header>
        <div class="ticket-dashboard-wrap"><ErrorMessage :message="error" /><TicketDashboard :settings="settings" :counts="counts" @open="select" /></div>
      </template>
      <template v-else>
        <header class="page-head">
          <h2>{{ heading }}</h2><small v-if="activeItem?.count != null">{{ activeItem.count }}</small>
          <div class="page-head-actions">
            <Button variant="outline" icon-left="chart-column" label="Dashboard" @click="view = 'dashboard'" />
            <Button v-if="settings.can_manage" variant="outline" icon-left="settings" label="Ticket settings" @click="view = 'settings'" />
            <Button v-if="typeOptions.length" variant="solid" icon-left="plus" label="New ticket" @click="creating = true" />
          </div>
        </header>
        <div v-if="stats.length" class="page-stats">
          <button v-for="stat in stats" :key="stat.label" type="button" class="page-stat" :title="stat.hint" :aria-label="`${stat.label}: ${stat.value}. Show these tickets`" @click="openStat(stat)">
            <span>{{ stat.label }}</span><strong>{{ stat.value }}</strong><small>{{ stat.hint }}</small>
          </button>
        </div>
        <div class="page-bar">
          <TextInput v-model="filters.query" class="page-search" type="search" placeholder="Filter tickets" aria-label="Search tickets" maxlength="80"><template #prefix><FeatherIcon name="search" /></template></TextInput>
          <select class="page-select" aria-label="Ticket status" :value="filters.ticket_status" @change="pickStatus($event.target.value)">
            <option v-for="option in statusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
          <span v-if="filterLabel" class="ticket-filter-label">{{ filterLabel }}<Button label="Clear filter" variant="ghost" @click="resetFilters" /></span>
        </div>
        <div v-if="error" class="page-feedback"><ErrorMessage :message="error" /></div>
        <LoadingRows v-if="busy && !page.items.length" label="Loading tickets…" />
        <table v-if="page.items.length" class="page-table ticket-table">
          <thead><tr><th>Ticket</th><th>Contact</th><th>Linked record</th><th v-for="field in page.group_fields" :key="field.fieldname">{{ field.label }}</th><th>Assignee</th><th>Status</th><th>Updated</th></tr></thead>
          <tbody>
            <tr v-for="row in page.items" :key="row.name" :class="{ selected: selected?.name === row.name }" tabindex="0" @click="select(row)" @keydown.enter.prevent="select(row)">
              <td class="cell-main"><b class="cell-title" :title="recordTitle(row, 'Ticket')">{{ recordTitle(row, 'Ticket') }}</b><small>{{ row.name }} · {{ dateTime(row.creation) }}</small></td>
              <td data-label="Contact"><span v-if="row.contact_title || row.business_title"><span class="ticket-contact">{{ row.contact_title || row.business_title }}</span><small>{{ row.contact_title && row.business_title ? row.business_title : row.business_doctype ? typeLabel(row.business_doctype) : 'Not linked' }}</small></span><span v-else class="muted">—</span></td>
              <td data-label="Linked record"><span v-if="row.business_name"><span class="page-mono ticket-record" :title="row.business_name">{{ row.business_name }}</span><small>{{ typeLabel(row.business_doctype) }}</small></span><span v-else class="muted">—</span></td>
              <td v-for="field in page.group_fields" :key="field.fieldname" :data-label="field.label">{{ row.group_values?.[field.fieldname] || 'Not set' }}</td>
              <td data-label="Assignee"><span class="page-person" :class="{ muted: !row.assigned_to }"><UserAvatar v-if="row.assigned_to" :user="row.assigned_to" :label="linkedTitle('User', row.assigned_to)" size="sm" />{{ linkedTitle('User', row.assigned_to, 'Unassigned') }}</span></td>
              <td data-label="Status"><Badge :label="look(row).label" :theme="look(row).theme" /></td>
              <td data-label="Updated" :title="dateTime(row.modified || row.creation)">{{ listTime(row.modified || row.creation) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!busy && !error && !page.items.length" class="page-empty">
          <strong>No tickets here</strong><p>{{ hasFilters ? 'Try another view or clear the search.' : 'Tickets will appear here when they are created.' }}</p>
          <Button v-if="hasFilters" label="Show all tickets" variant="outline" @click="resetFilters" />
        </div>
        <div v-if="page.next" ref="ticketSentinel" class="h-px" aria-hidden="true" />
      </template>
    </main>
    <NewTicketDialog v-model="creating" :business-types="typeOptions" @created="created" />
    <TicketDialog v-if="selected" :ticket="selected" :settings="settings" :error="saveError" :busy="busy" :ai-enabled="aiEnabled" @update="update" @close="close" />
  </div>
</template>

<style scoped>
.ticket-dashboard-wrap { display:flex; flex-direction:column; gap:12px; padding:16px 20px; }
.ticket-filter-label { display:inline-flex; align-items:center; gap:4px; color:var(--relay-ink-3); font-size:13px; }
.ticket-contact { display:block; max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ticket-table td.muted, .ticket-table .muted { color:var(--relay-ink-soft); }
.ticket-record { display:block; max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ticket-table td:last-child { white-space:nowrap; }
</style>
