<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { Button, ErrorMessage, FormControl } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { useTask } from '../../composables/useTask'
import {
  MONTHS, categoryRows, chartBars, formatCount, formatFetched, formatMoney, formatPercent, monthRows, summaryCards, templateRows, yearOptions,
} from '../../services/billing'
import LoadingRows from '../LoadingRows.vue'

const props = defineProps({ account: { type: String, default: '' } })
const years = yearOptions()
const year = ref(years[0]), mode = ref('monthly'), data = ref(null)
const { busy, error, notice, run } = useTask()

const currency = computed(() => data.value?.currency || '')
const money = value => formatMoney(value, currency.value)
const cards = computed(() => summaryCards(data.value))
const months = computed(() => monthRows(data.value?.months))
const bars = computed(() => chartBars(months.value))
const categories = computed(() => categoryRows(data.value?.categories, data.value?.total))
const templates = computed(() => templateRows(data.value?.templates))
const templateMonths = computed(() => MONTHS.map((label, index) => ({ label, index })).filter(({ index }) => templates.value.some(row => row.months[index])))
const columnTotal = key => months.value.reduce((sum, row) => sum + row[key], 0)
const countColumns = [['messages', 'Messages'], ['marketing', 'Marketing'], ['utility', 'Utility'], ['authentication', 'Authentication'], ['service_free', 'Service free']]
const moneyColumns = [['meta_cost', 'Meta charge'], ['margin_amount', 'Margin'], ['total', 'Total']]

async function load() {
  if (!props.account) return
  data.value = await coreApi('billing.get_billing', { account: props.account, year: year.value })
}
async function refresh() {
  const result = await coreApi('billing.refresh_billing', { account: props.account, year: year.value }, true)
  await load()
  notice.value = `Read ${formatCount(result.data_points)} Meta data points into ${formatCount(result.rows)} rows.`
}
watch(() => [props.account, year.value], () => run(load))
onMounted(() => run(load))
</script>

<template>
  <div class="v1-content billing">
    <header class="billing-toolbar">
      <FormControl v-model="year" class="billing-year" type="select" label="Year" :options="years" :disabled="busy" />
      <div class="billing-toggle" role="group" aria-label="Billing view">
        <button v-for="option in ['monthly', 'yearly']" :key="option" type="button" :aria-pressed="mode === option" @click="mode = option">{{ option === 'monthly' ? 'Monthly' : 'Yearly' }}</button>
      </div>
      <span class="billing-updated">Last updated {{ formatFetched(data?.fetched_at) }}</span>
      <Button label="Refresh" icon-left="refresh-cw" :loading="busy" :disabled="!account" @click="run(refresh)" />
    </header>
    <ErrorMessage :message="error" /><p v-if="notice" role="status" class="workspace-success">{{ notice }}</p>
    <p v-if="!account" class="billing-empty">Set the Hub account in Settings to see WhatsApp billing.</p>
    <LoadingRows v-else-if="!data && busy" label="Loading billing…" :count="4" />
    <template v-else-if="data">
      <div class="billing-cards">
        <div v-for="card in cards" :key="card.label" class="workflow-card billing-stat" :class="{ 'is-accent': card.accent }">
          <span>{{ card.label }}</span><strong>{{ card.value }}</strong><small>{{ card.hint }}</small>
        </div>
      </div>
      <p class="billing-note">Margin {{ formatPercent(data.margin_percent) }} · Set by System Manager in Settings</p>

      <template v-if="mode === 'monthly'">
        <section class="workflow-card billing-panel" aria-labelledby="billing-chart-title">
          <h3 id="billing-chart-title">Total to bill per month</h3>
          <div class="billing-chart" role="img" :aria-label="bars.map(bar => `${bar.label} ${money(bar.total)}`).join(', ')">
            <div v-for="bar in bars" :key="bar.label" class="billing-bar" :title="`${bar.label}: ${money(bar.total)}`">
              <span class="billing-bar-fill" :style="{ height: bar.height + '%' }" /><small>{{ bar.label }}</small>
            </div>
          </div>
        </section>
        <section class="workflow-card billing-panel" aria-labelledby="billing-months-title">
          <h3 id="billing-months-title">By month</h3>
          <div class="billing-table-wrap" tabindex="0">
            <table class="billing-table">
              <thead><tr><th scope="col">Month</th><th v-for="[key, label] in [...countColumns, ...moneyColumns]" :key="key" scope="col" class="num">{{ label }}</th></tr></thead>
              <tbody>
                <tr v-for="row in months" :key="row.period" :class="{ 'is-empty': !row.messages }">
                  <th scope="row">{{ row.label }}</th>
                  <td v-for="[key] in countColumns" :key="key" class="num">{{ formatCount(row[key]) }}</td>
                  <td v-for="[key] in moneyColumns" :key="key" class="num" :class="{ strong: key === 'total' }">{{ money(row[key]) }}</td>
                </tr>
              </tbody>
              <tfoot><tr><th scope="row">Total</th>
                <td v-for="[key] in countColumns" :key="key" class="num">{{ formatCount(columnTotal(key)) }}</td>
                <td v-for="[key] in moneyColumns" :key="key" class="num">{{ money(data.total[key]) }}</td>
              </tr></tfoot>
            </table>
          </div>
        </section>
      </template>

      <section v-else class="workflow-card billing-panel" aria-labelledby="billing-categories-title">
        <h3 id="billing-categories-title">By category · {{ data.year }}</h3>
        <div class="billing-table-wrap" tabindex="0">
          <table class="billing-table">
            <thead><tr><th scope="col">Category</th><th scope="col" class="num">Messages</th><th scope="col" class="num">Meta charge</th><th scope="col" class="num">Share</th><th scope="col" class="num">Margin</th><th scope="col" class="num">Total</th></tr></thead>
            <tbody>
              <tr v-for="row in categories" :key="row.category">
                <th scope="row">{{ row.label }}</th><td class="num">{{ formatCount(row.volume) }}</td><td class="num">{{ money(row.meta_cost) }}</td>
                <td class="num">{{ formatPercent(row.share) }}</td><td class="num">{{ money(row.margin_amount) }}</td><td class="num strong">{{ money(row.total) }}</td>
              </tr>
              <tr v-if="!categories.length"><td colspan="6" class="billing-empty">No Meta charges for {{ data.year }}.</td></tr>
            </tbody>
            <tfoot><tr><th scope="row">Total</th><td class="num">{{ formatCount(data.total.volume) }}</td><td class="num">{{ money(data.total.meta_cost) }}</td><td class="num" /><td class="num">{{ money(data.total.margin_amount) }}</td><td class="num">{{ money(data.total.total) }}</td></tr></tfoot>
          </table>
        </div>
      </section>

      <section class="workflow-card billing-panel" aria-labelledby="billing-templates-title">
        <h3 id="billing-templates-title">By template</h3>
        <p v-if="!templates.length" class="billing-empty">No template messages were sent from Relay in {{ data.year }}.</p>
        <div v-else class="billing-table-wrap" tabindex="0">
          <table class="billing-table">
            <thead><tr><th scope="col">Template</th><th scope="col">Category</th>
              <template v-if="mode === 'monthly'"><th v-for="month in templateMonths" :key="month.label" scope="col" class="num">{{ month.label }}</th></template>
              <th scope="col" class="num">{{ mode === 'monthly' ? 'Total' : 'Messages sent' }}</th></tr></thead>
            <tbody>
              <tr v-for="row in templates" :key="row.template">
                <th scope="row">{{ row.template }}</th><td>{{ row.category || '—' }}</td>
                <template v-if="mode === 'monthly'"><td v-for="month in templateMonths" :key="month.label" class="num">{{ formatCount(row.months[month.index]) }}</td></template>
                <td class="num strong">{{ formatCount(row.total) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.billing { display:flex; flex-direction:column; gap:14px; }
.billing-toolbar { display:flex; flex-wrap:wrap; align-items:flex-end; gap:10px 12px; }
.billing-year { width:120px; }
.billing-toggle { display:inline-flex; padding:2px; gap:2px; border:1px solid var(--relay-stroke); border-radius:var(--relay-radius); background:var(--relay-layer); }
.billing-toggle button { min-height:28px; padding:0 12px; border-radius:6px; font-size:13px; color:var(--ink-gray-7); }
.billing-toggle button[aria-pressed=true] { background:var(--relay-accent-soft); color:var(--relay-accent-text); font-weight:600; }
.billing-updated { margin-left:auto; align-self:center; font-size:12px; color:var(--ink-gray-5); }
.billing-cards { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }
.billing-stat { gap:4px !important; padding:14px 16px !important; }
.billing-stat span { font-size:12px; font-weight:600; color:var(--ink-gray-5); }
.billing-stat strong { font-size:22px; font-weight:600; color:var(--ink-gray-9); font-variant-numeric:tabular-nums; }
.billing-stat small { font-size:12px; color:var(--ink-gray-5); }
.billing-stat.is-accent strong { color:var(--relay-accent-text); }
.billing-note { font-size:12px; color:var(--ink-gray-5); margin-top:-6px; }
.billing-panel { gap:12px !important; padding:16px !important; min-width:0; }
.billing-panel h3 { font-size:14px; }
.billing-chart { display:grid; grid-template-columns:repeat(12,minmax(0,1fr)); align-items:end; gap:8px; height:160px; }
.billing-bar { display:flex; flex-direction:column; align-items:center; justify-content:flex-end; gap:6px; height:100%; min-width:0; }
.billing-bar-fill { width:100%; max-width:36px; min-height:2px; border-radius:4px 4px 0 0; background:var(--relay-accent); transition:height var(--relay-normal) var(--relay-ease); }
.billing-bar small { font-size:11px; color:var(--ink-gray-5); }
.billing-table-wrap { overflow-x:auto; min-width:0; border:1px solid var(--relay-stroke); border-radius:var(--relay-radius); }
.billing-table { width:100%; border-collapse:collapse; font-size:13px; font-variant-numeric:tabular-nums; }
.billing-table :is(th,td) { padding:8px 12px; text-align:left; white-space:nowrap; border-bottom:1px solid var(--relay-stroke); }
.billing-table thead th { font-size:12px; font-weight:600; color:var(--ink-gray-5); background:var(--relay-layer); }
.billing-table tbody th { font-weight:500; color:var(--ink-gray-8); }
.billing-table tbody tr:hover { background:var(--relay-hover); }
.billing-table tr.is-empty :is(th,td) { color:var(--ink-gray-4); }
.billing-table tfoot :is(th,td) { font-weight:600; color:var(--ink-gray-9); border-bottom:0; background:var(--relay-layer); }
.billing-table .num { text-align:right; }
.billing-table .strong { font-weight:600; color:var(--ink-gray-9); }
.billing-empty { font-size:13px; color:var(--ink-gray-5); white-space:normal !important; }
@media (max-width:1100px) { .billing-cards { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:768px) {
  .billing-updated { margin-left:0; width:100%; order:4; }
  .billing-stat strong { font-size:18px; }
  .billing-chart { gap:4px; height:120px; }
  .billing-bar small { font-size:10px; }
}
</style>
