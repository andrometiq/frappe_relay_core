<script setup>
import { computed, onMounted, ref } from 'vue'
import { Button, ErrorMessage } from '@relay/ui'
import LoadingRows from '../LoadingRows.vue'
import { coreApi } from '../../services/coreApi'
import { linkedTitle } from '../../services/linkedTitle'
import { assigneeChartRows, chartRows, ticketFilterRoute, ticketTotals } from '../../services/ticketSettings'
import { useRealtimeRefresh } from '../../composables/useRealtimeRefresh'

const props = defineProps({ settings: Object })
const counts = ref(null), error = ref(''), expanded = ref(false)
let generation = 0

async function load() {
  const current = ++generation
  try {
    const result = await coreApi('tickets.dashboard')
    if (current === generation) { counts.value = result; error.value = '' }
  } catch (e) { if (current === generation) error.value = e.message }
}
const totals = computed(() => ticketTotals(props.settings, counts.value?.statuses || []))
const charts = computed(() => counts.value ? [
  { title: 'Tickets per person', rows: assigneeChartRows(counts.value.assignees, user => user ? linkedTitle('User', user, user) : 'Unassigned', expanded.value), expandable: counts.value.assignees.length > 8 },
  { title: 'Tickets per type', rows: chartRows(counts.value.types, 'ticket_type', type => type || 'No type').map(row => ({ ...row, filters: { ticket_type: row.key } })) },
] : [])
onMounted(load)
useRealtimeRefresh(['Relay Ticket'], ['tickets'], load)
</script>

<template>
  <div class="ticket-dashboard">
    <ErrorMessage :message="error" />
    <LoadingRows v-if="!counts && !error" label="Loading dashboard…" />
    <template v-if="counts">
      <div class="ticket-totals">
        <div class="workflow-card ticket-total"><span>Open</span><strong>{{ totals.open }}</strong></div>
        <div class="workflow-card ticket-total"><span>Closed</span><strong>{{ totals.closed }}</strong></div>
      </div>
      <section v-for="chart in charts" :key="chart.title" class="workflow-card ticket-chart" :aria-label="chart.title">
        <h3>{{ chart.title }}</h3>
        <p v-if="!chart.rows.length" class="ticket-chart__empty">No tickets yet.</p>
        <ul>
          <li v-for="row in chart.rows" :key="row.key" :title="row.label + ': ' + row.tickets">
            <a class="ticket-chart__link" :href="ticketFilterRoute(row.filters)" :aria-label="`Show ${row.tickets} tickets: ${row.label}`">
            <span class="ticket-chart__label">{{ row.label }}</span>
            <span class="ticket-chart__track"><span class="ticket-chart__bar" :style="{ width: row.width + '%' }" /></span>
            <span class="ticket-chart__value">{{ row.tickets }}</span>
            </a>
          </li>
        </ul>
        <Button v-if="chart.expandable" variant="ghost" :label="expanded ? 'Show top eight' : 'Show all people'" :aria-expanded="expanded" @click="expanded = !expanded" />
      </section>
    </template>
  </div>
</template>

<style scoped>
.ticket-dashboard { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr)); gap: 16px; align-items: start; }
.ticket-dashboard > :deep(.relay-error), .ticket-dashboard > .loading-rows { grid-column: 1 / -1; }
.ticket-totals { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; grid-column: 1 / -1; }
.ticket-total { padding: 24px; display: flex; flex-direction: column; gap: 4px; }
.ticket-total span { font-size: 13px; color: var(--ink-gray-6); }
.ticket-total strong { font-size: 28px; font-weight: 600; color: var(--ink-gray-9); font-variant-numeric: tabular-nums; }
.ticket-chart { padding: 24px; display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.ticket-chart h3 { font-size: 14px; font-weight: 600; }
.ticket-chart ul { display: flex; flex-direction: column; gap: 8px; }
.ticket-chart li a.ticket-chart__link { display: grid; grid-template-columns: minmax(80px, 160px) minmax(0, 1fr) auto; align-items: center; gap: 8px; font-size: 13px; min-height: 36px; border-radius: 4px; }
.ticket-chart li a:hover { background: var(--surface-gray-2); }
.ticket-chart li a:focus-visible { outline: 2px solid var(--outline-blue-2); outline-offset: 2px; }
.ticket-chart__label { overflow-wrap: anywhere; color: var(--ink-gray-8); }
.ticket-chart__track { height: 10px; border-radius: 4px; background: var(--surface-gray-2); overflow: hidden; }
.ticket-chart__bar { display: block; height: 100%; min-width: 4px; border-radius: 4px; background: var(--relay-accent); }
.ticket-chart__value { min-width: 32px; text-align: right; color: var(--ink-gray-7); font-variant-numeric: tabular-nums; }
.ticket-chart__empty { font-size: 13px; color: var(--ink-gray-6); }
</style>
