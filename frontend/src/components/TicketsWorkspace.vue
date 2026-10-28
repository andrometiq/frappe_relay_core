<script setup>
import { useLoadMore } from '../composables/useLoadMore'
import { useDebouncedSearch } from '../composables/useDebouncedSearch'
import { recordTitle } from '../services/recordTitle'
import { linkedTitle } from '../services/linkedTitle'
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue'
import { Badge, Button, ErrorMessage, FeatherIcon, TextInput, toast } from '@relay/ui'
import TicketSettings from './TicketSettings.vue'
import TicketDashboard from './tickets/TicketDashboard.vue'
import TicketDialog from './tickets/TicketDialog.vue'
import { useTicketSettings } from '../composables/useTicketSettings'
import { emptyTicketFilters, pickerOptions, statusLook } from '../services/ticketSettings'
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
const filters = ref(emptyTicketFilters())
const page = ref({ items: [] }), selected = ref(null), error = ref('')
const listBusy = ref(false), detailBusy = ref(false), saving = ref(false)
const busy = computed(() => listBusy.value || detailBusy.value || saving.value)
const statusTabs = computed(() => pickerOptions(settings.value.statuses, 'All'))
const look = ticket => statusLook(settings.value, ticket)
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
function dismiss() { ++detailGeneration; selected.value = null; detailBusy.value = false }
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
const updated = {
  claim: () => 'You took over. AI is stopped for this conversation.',
  resume_ai: () => 'AI resumed',
  close_and_release: () => 'Ticket closed',
  update_status: values => 'Status changed to ' + (settings.value.statuses.find(row => row.name === values.status)?.label || values.status),
  assign: values => values.user ? 'Assigned to ' + linkedTitle('User', values.user) : 'Owner removed',
}
async function update(method, values = {}) {
  const name = selected.value.name
  saving.value = true; error.value = ''
  try {
    await coreApi('tickets.' + method, { name, ...values }, true)
    if (selected.value?.name === name) await load()
    toast(updated[method](values))
  } catch (e) { error.value = e.message }
  finally { saving.value = false }
}
useDebouncedSearch(() => JSON.stringify(filters.value), () => load(), () => { ++generation; page.value = { items: [] }; listBusy.value = true })
onMounted(() => { loadSettings().catch(e => { error.value = e.message }) })
onMounted(() => { load(); readRoute(); window.addEventListener('popstate', readRoute) })
onBeforeUnmount(() => window.removeEventListener('popstate', readRoute))
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
        <Button v-if="settings.can_manage" variant="outline" icon-left="settings" label="Ticket settings" class="ticket-page-head__settings" @click="view = 'settings'" />
      </div>
      <ErrorMessage :message="error" />
      <TicketDashboard v-if="view === 'dashboard'" :settings="settings" />
      <template v-else>
        <div class="ticket-toolbar">
          <TextInput v-model="filters.query" class="ticket-toolbar__search" type="search" placeholder="Search tickets" aria-label="Search tickets" maxlength="80"><template #prefix><FeatherIcon name="search" /></template></TextInput>
          <button type="button" class="ticket-chip" :aria-pressed="!!filters.mine" @click="setFilter({ mine: filters.mine ? 0 : 1 })"><FeatherIcon name="user" :size="14" />Assigned to me</button>
        </div>
        <div class="ticket-status-tabs" role="tablist" aria-label="Ticket status">
          <button v-for="option in statusTabs" :key="option.value" type="button" role="tab" :aria-selected="filters.ticket_status === option.value" @click="setFilter({ ticket_status: option.value })">{{ option.label }}</button>
        </div>
        <LoadingRows v-if="busy && !page.items.length" label="Loading tickets…" />
        <ul v-if="page.items.length" class="ticket-list">
          <li v-for="row in page.items" :key="row.name">
            <button type="button" class="ticket-row" :aria-label="'Open ticket: ' + recordTitle(row, 'Ticket')" @click="select(row)">
              <span class="ticket-row__main">
                <strong>{{ recordTitle(row, 'Ticket') }}</strong>
                <small>{{ [row.name, row.ticket_type, row.business_name ? linkedTitle(row.business_doctype, row.business_name) : '', dateTime(row.creation)].filter(Boolean).join(' · ') }}</small>
              </span>
              <span class="ticket-row__side">
                <span :class="{ 'ticket-unassigned': !row.assigned_to }">{{ linkedTitle('User', row.assigned_to, 'Unassigned') }}</span>
                <Badge :label="look(row).label" :theme="look(row).theme" />
              </span>
            </button>
          </li>
        </ul>
        <WorkspaceState v-if="!busy && !error && !page.items.length" class="ticket-empty" title="No tickets here" description="Pick another status, or turn off Assigned to me." icon="bookmark" />
        <div v-if="page.next" ref="ticketSentinel" class="h-px" aria-hidden="true" />
      </template>
    </template>
    <TicketDialog v-if="selected" :ticket="selected" :settings="settings" :busy="busy" :ai-enabled="aiEnabled" @update="update" @close="close" />
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
.ticket-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.ticket-toolbar__search { flex: 1 1 220px; min-width: 0; max-width: 360px; }
.ticket-chip { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 12px; border: 1px solid var(--outline-gray-2); border-radius: 999px; background: var(--surface-white); font-size: 13px; color: var(--ink-gray-7); white-space: nowrap; }
.ticket-chip[aria-pressed=true] { border-color: var(--outline-blue-1, var(--relay-accent)); background: var(--surface-blue-1, var(--relay-accent-soft)); color: var(--ink-blue-3); font-weight: 600; }
.ticket-list { display: flex; flex-direction: column; gap: 8px; }
.ticket-row { display: flex; width: 100%; align-items: center; gap: 16px; padding: 14px 16px; border: 1px solid var(--outline-gray-2); border-radius: 10px; background: var(--surface-white); text-align: left; }
.ticket-row:hover { background: var(--surface-gray-2); }
.ticket-row__main { display: flex; flex: 1; min-width: 0; flex-direction: column; gap: 4px; }
.ticket-row__main strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; color: var(--ink-gray-9); }
.ticket-row__main small { font-size: 12.5px; color: var(--ink-gray-6); overflow-wrap: anywhere; }
.ticket-row__side { display: flex; flex: none; align-items: center; gap: 12px; font-size: 13px; color: var(--ink-gray-7); }
.ticket-unassigned { color: var(--relay-amber, #b86e00); }
.ticket-empty { min-height: min(50vh, 360px); }
@media (max-width: 768px) {
  .ticket-page-head__settings :deep(.relay-button__label) { display: none; }
  .ticket-toolbar__search { flex-basis: 100%; max-width: none; }
  .ticket-row { flex-direction: column; align-items: stretch; gap: 8px; }
  .ticket-row__side { justify-content: space-between; }
}
</style>
