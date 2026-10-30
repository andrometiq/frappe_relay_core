<script setup>
import { computed, onMounted, ref } from 'vue'
import { Users } from '@lucide/vue'
import { Avatar, Badge, ErrorMessage } from '@relay/ui'
import LoadingRows from '../LoadingRows.vue'
import { coreApi } from '../../services/coreApi'
import { linkedTitle } from '../../services/linkedTitle'
import { recordTitle } from '../../services/recordTitle'
import { assigneeChartRows, chartRows, statusLook, ticketFilterRoute } from '../../services/ticketSettings'
import { useRealtimeRefresh } from '../../composables/useRealtimeRefresh'
import { relativeTime } from '../relativeTime'

const props = defineProps({ settings: Object })
const emit = defineEmits(['open'])
const counts = ref(null), error = ref('')
let generation = 0

async function load() {
  const current = ++generation
  try {
    const result = await coreApi('tickets.dashboard')
    if (current === generation) { counts.value = result; error.value = '' }
  } catch (e) { if (current === generation) error.value = e.message }
}
const person = user => user ? linkedTitle('User', user, user) : 'Unassigned'
const kpis = computed(() => {
  const totals = counts.value.totals
  return [
    { label: 'Open', value: totals.open, filters: { state: 'Open' } },
    { label: 'Assigned', hint: 'Open tickets with an owner', value: totals.assigned, filters: { state: 'Open', assigned: 1 } },
    { label: 'Unassigned', value: totals.unassigned, filters: { state: 'Open', assigned_to: '' } },
    { label: 'Resolved today', value: totals.resolved_today, filters: { resolved_today: 1 } },
  ]
})
const oldest = computed(() => counts.value.oldest_open)
const assignees = computed(() => assigneeChartRows(counts.value.assignees, person))
const statuses = computed(() => {
  const order = props.settings.statuses.map(row => row.name)
  const rows = [...counts.value.statuses].sort((a, b) => order.indexOf(a.ticket_status) - order.indexOf(b.ticket_status))
  return chartRows(rows, 'ticket_status', status => statusLook(props.settings, { ticket_status: status }).label)
    .map(row => ({ ...row, theme: statusLook(props.settings, { ticket_status: row.key }).theme, filters: { ticket_status: row.key } }))
})
const businessTypes = computed(() => chartRows(counts.value.business_types, 'business_doctype', type => type || 'Not linked')
  .map(row => ({ ...row, filters: row.key ? { state: 'Open', business_type: row.key } : { state: 'Open', unlinked: 1 } })))
const panels = computed(() => [
  { key: 'assignees', title: 'Open tickets by assignee', rows: assignees.value, avatars: true },
  { key: 'statuses', title: 'Tickets by status', rows: statuses.value },
  { key: 'business', title: 'Open tickets by business type', rows: businessTypes.value },
])
onMounted(load)
useRealtimeRefresh(['Relay Ticket'], ['tickets'], load)
</script>

<template>
  <div class="ticket-dashboard">
    <ErrorMessage :message="error" />
    <LoadingRows v-if="!counts && !error" label="Loading dashboard…" />
    <template v-if="counts">
      <div class="ticket-kpis">
        <a v-for="kpi in kpis" :key="kpi.label" class="ticket-kpi" :href="ticketFilterRoute(kpi.filters)" :title="kpi.hint" :aria-label="`${kpi.label}: ${kpi.value}. Show these tickets`">
          <span>{{ kpi.label }}</span><strong>{{ kpi.value }}</strong>
        </a>
        <button v-if="oldest" type="button" class="ticket-kpi" :title="recordTitle(oldest, 'Ticket')" :aria-label="`Oldest open ticket, opened ${relativeTime(oldest.creation)}. Open it`" @click="emit('open', oldest)">
          <span>Oldest open</span><strong>{{ relativeTime(oldest.creation).replace(' ago', '') }}</strong>
        </button>
        <div v-else class="ticket-kpi"><span>Oldest open</span><strong>—</strong></div>
      </div>
      <section v-for="panel in panels" :key="panel.key" :class="['workflow-card', 'ticket-panel', 'ticket-panel--' + panel.key]" :aria-label="panel.title">
        <h3>{{ panel.title }}</h3>
        <p v-if="!panel.rows.length" class="ticket-panel__empty">No open tickets.</p>
        <ul v-else>
          <li v-for="row in panel.rows" :key="row.key">
            <a class="ticket-bar" :href="ticketFilterRoute(row.filters)" :title="(row.title || row.label) + ': ' + row.tickets" :aria-label="`Show ${row.tickets} tickets: ${row.label}`">
              <span class="ticket-bar__label">
                <span v-if="panel.avatars && row.key === 'others'" class="ticket-bar__group" aria-hidden="true"><Users :stroke-width="1.7" /></span>
                <Avatar v-else-if="panel.avatars" :label="row.key ? row.label : ''" size="sm" />
                <Badge v-else-if="row.theme" :label="row.label" :theme="row.theme" />
                <span v-if="!row.theme">{{ row.label }}</span>
              </span>
              <span class="ticket-bar__track"><span class="ticket-bar__fill" :style="{ width: row.width + '%' }" /></span>
              <span class="ticket-bar__value">{{ row.tickets }}</span>
            </a>
          </li>
        </ul>
      </section>
      <section class="workflow-card ticket-panel ticket-panel--recent" aria-label="Recent open tickets">
        <h3>Recent open tickets</h3>
        <p v-if="!counts.recent.length" class="ticket-panel__empty">No open tickets.</p>
        <ul v-else>
          <li v-for="ticket in counts.recent" :key="ticket.name">
            <button type="button" class="ticket-recent" :title="recordTitle(ticket, 'Ticket')" @click="emit('open', ticket)">
              <span class="ticket-recent__title"><strong>{{ recordTitle(ticket, 'Ticket') }}</strong><small>{{ ticket.name }} · {{ person(ticket.assigned_to) }}</small></span>
              <small class="ticket-recent__time">{{ relativeTime(ticket.creation) }}</small>
            </button>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.ticket-dashboard { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); grid-template-areas: 'kpis kpis' 'assignees statuses' 'assignees business' 'recent recent'; gap: 12px; align-items: start; }
.ticket-dashboard > :deep(.relay-error), .ticket-dashboard > .loading-rows { grid-column: 1 / -1; }
.ticket-kpis { grid-area: kpis; display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.ticket-dashboard .ticket-kpis .ticket-kpi { display: flex; align-items: stretch; min-height: 0; flex-direction: column; gap: 2px; min-width: 0; padding: 12px 14px; border: 1px solid var(--outline-gray-2); border-radius: 8px; background: var(--surface-white); text-align: left; }
a.ticket-kpi:hover, button.ticket-kpi:hover { background: var(--surface-gray-1); }
.ticket-kpi span { font-size: 12px; color: var(--ink-gray-6); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ticket-kpi strong { font-size: 22px; line-height: 28px; font-weight: 600; color: var(--ink-gray-9); font-variant-numeric: tabular-nums; }
.ticket-panel { padding: 16px; gap: 10px; min-width: 0; }
.ticket-panel--assignees { grid-area: assignees; }
.ticket-panel--statuses { grid-area: statuses; }
.ticket-panel--business { grid-area: business; }
.ticket-panel--recent { grid-area: recent; }
.ticket-panel h3 { font-size: 13px; font-weight: 600; color: var(--ink-gray-8); }
.ticket-panel ul { display: flex; flex-direction: column; gap: 2px; }
.ticket-panel__empty { font-size: 13px; color: var(--ink-gray-6); }
.ticket-dashboard .ticket-panel a.ticket-bar { display: grid; grid-template-columns: minmax(0, 45%) minmax(40px, 1fr) 40px; align-items: center; gap: 10px; min-height: 36px; padding: 0 6px; border-radius: 6px; font-size: 13px; }
.ticket-bar__label { display: flex; align-items: center; gap: 8px; min-width: 0; color: var(--ink-gray-8); }
.ticket-bar__label > span:last-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ticket-bar__track { height: 8px; border-radius: 4px; background: var(--surface-gray-4); overflow: hidden; }
.ticket-bar__group { display: inline-flex; flex: none; align-items: center; justify-content: center; width: 28px; height: 28px; border: 1px solid var(--outline-gray-2); border-radius: 50%; background: var(--surface-gray-3); color: var(--ink-gray-7); }
.ticket-bar__group svg { width: 60%; height: 60%; }
.ticket-bar__fill { display: block; height: 100%; min-width: 4px; border-radius: 4px; background: var(--relay-accent); }
.ticket-bar__value { text-align: right; color: var(--ink-gray-7); font-variant-numeric: tabular-nums; }
.ticket-recent { display: flex; align-items: center; gap: 12px; width: 100%; min-height: 44px; padding: 4px 6px; border-radius: 6px; text-align: left; }
.ticket-recent__title { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.ticket-recent__title strong, .ticket-recent__title small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ticket-recent__title strong { font-size: 13px; font-weight: 500; color: var(--ink-gray-9); }
.ticket-recent__title small, .ticket-recent__time { font-size: 12px; color: var(--ink-gray-6); }
.ticket-recent__time { flex: none; }
:is(.ticket-bar, .ticket-recent):hover { background: var(--surface-gray-2); }
:is(.ticket-kpi, .ticket-bar, .ticket-recent):focus-visible { outline: 2px solid var(--relay-accent); outline-offset: 2px; }
@media (max-width: 900px) {
  .ticket-dashboard { grid-template-columns: minmax(0, 1fr); grid-template-areas: 'kpis' 'assignees' 'statuses' 'business' 'recent'; }
  .ticket-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ticket-kpis > :last-child { grid-column: 1 / -1; }
  .ticket-dashboard .ticket-panel a.ticket-bar { grid-template-columns: minmax(0, 1fr) 40px; grid-template-areas: 'label value' 'track track'; row-gap: 6px; padding: 6px; }
  .ticket-bar__label { grid-area: label; }
  .ticket-bar__track { grid-area: track; }
  .ticket-bar__value { grid-area: value; }
}
</style>
