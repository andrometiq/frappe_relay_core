<script setup>
import { computed, onMounted, ref } from 'vue'
import { ErrorMessage } from '@relay/ui'
import LoadingRows from '../LoadingRows.vue'
import { coreApi } from '../../services/coreApi'
import { linkedTitle } from '../../services/linkedTitle'
import { chartRows, ticketTotals } from '../../services/ticketSettings'
import { useRealtimeRefresh } from '../../composables/useRealtimeRefresh'

const props = defineProps({ settings: Object })
const counts = ref(null), error = ref('')
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
  { title: 'Tickets per person', rows: chartRows(counts.value.assignees, 'assigned_to', user => user ? linkedTitle('User', user, user) : 'Unassigned') },
  { title: 'Tickets per type', rows: chartRows(counts.value.types, 'ticket_type', type => type || 'No type') },
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
            <span class="ticket-chart__label">{{ row.label }}</span>
            <span class="ticket-chart__track"><span class="ticket-chart__bar" :style="{ width: row.width + '%' }" /></span>
            <span class="ticket-chart__value">{{ row.tickets }}</span>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>

<style scoped>
.ticket-dashboard { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr)); gap: 12px; align-items: start; }
.ticket-dashboard > :deep(.relay-error), .ticket-dashboard > .loading-rows { grid-column: 1 / -1; }
.ticket-totals { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; grid-column: 1 / -1; }
.ticket-total { display: flex; flex-direction: column; gap: 4px; }
.ticket-total span { font-size: 13px; color: var(--ink-gray-6); }
.ticket-total strong { font-size: 28px; font-weight: 600; color: var(--ink-gray-9); font-variant-numeric: tabular-nums; }
.ticket-chart { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.ticket-chart h3 { font-size: 14px; font-weight: 600; }
.ticket-chart ul { display: flex; flex-direction: column; gap: 8px; }
.ticket-chart li { display: grid; grid-template-columns: minmax(80px, 160px) minmax(0, 1fr) auto; align-items: center; gap: 10px; font-size: 13px; }
.ticket-chart__label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink-gray-8); }
.ticket-chart__track { height: 10px; border-radius: 4px; background: var(--surface-gray-2); overflow: hidden; }
.ticket-chart__bar { display: block; height: 100%; min-width: 4px; border-radius: 4px; background: var(--relay-accent, #0f6cbd); }
.ticket-chart__value { min-width: 32px; text-align: right; color: var(--ink-gray-7); font-variant-numeric: tabular-nums; }
.ticket-chart__empty { font-size: 13px; color: var(--ink-gray-6); }
</style>
