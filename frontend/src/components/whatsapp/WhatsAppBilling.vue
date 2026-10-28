<script setup>
import { computed, inject, onMounted, ref, watch } from 'vue'
import { Button, ErrorMessage, FeatherIcon, FormControl } from '@relay/ui'
import { coreApi } from '../../services/coreApi'
import { useTask } from '../../composables/useTask'
import {
  categoryColor, chartBars, formatCount, formatFetched, formatMoney, formatRate, monthName, monthOptions, numberBills, statementLines, summaryCards,
  templateRows, yearOptions, yearRows,
} from '../../services/billing'
import LoadingRows from '../LoadingRows.vue'
import { numberName } from '../../services/whatsappNumbers'
import { sentenceCase } from '../../services/textCase'

const props = defineProps({ account: { type: String, default: '' } })
const capabilities = inject('relayCapabilities', ref({}))
const months = monthOptions(), years = yearOptions()
const view = ref('month'), month = ref(months[0].value), year = ref(years[0]), data = ref(null)
const { busy, error, notice, run } = useTask()

const dataYear = computed(() => view.value === 'month' ? month.value.slice(0, 4) : year.value)
const currency = computed(() => data.value?.currency || '')
const money = value => formatMoney(value, currency.value)
const loaded = computed(() => data.value && String(data.value.year) === dataYear.value)
const selectedMonth = computed(() => data.value?.months.find(row => row.period.startsWith(month.value)) || { lines: [], messages: 0, amount: 0 })
const statement = computed(() => view.value === 'month' ? selectedMonth.value : data.value?.total)
const periodLabel = computed(() => view.value === 'month' ? monthName(month.value) : year.value)
const cards = computed(() => summaryCards(statement.value, periodLabel.value, data.value?.numbers?.length || 0, currency.value))
const lines = computed(() => statementLines(selectedMonth.value.lines))
// One bill per WhatsApp number; rows from before per-number billing have no number and show as one statement.
const bills = computed(() => numberBills(data.value?.numbers, view.value === 'month' ? month.value : '')
  .map(bill => ({ ...bill, label: numberName(capabilities.value, bill.channel) || bill.label, lines: statementLines(bill.statement.lines) })))
const yearly = computed(() => yearRows(data.value?.months))
const bars = computed(() => chartBars(yearly.value))
const templates = computed(() => templateRows(data.value?.templates, view.value === 'month' ? month.value : ''))
const updated = computed(() => formatFetched(data.value?.fetched_at))

async function load() {
  if (!props.account) return
  data.value = await coreApi('billing.get_billing', { account: props.account, year: dataYear.value })
}
async function refresh() {
  await coreApi('billing.refresh_billing', { account: props.account, year: dataYear.value }, true)
  await load()
  notice.value = 'Bill updated.'
}
watch(() => [props.account, dataYear.value], () => run(load))
onMounted(() => run(load))
</script>

<template>
  <div class="v1-content billing">
    <header class="billing-toolbar">
      <div class="billing-toggle" role="group" aria-label="Billing period">
        <button v-for="option in [['month', 'Month'], ['year', 'Year']]" :key="option[0]" type="button" :aria-pressed="view === option[0]" @click="view = option[0]">{{ option[1] }}</button>
      </div>
      <FormControl v-if="view === 'month'" v-model="month" class="billing-period" type="select" aria-label="Month" :options="months" :disabled="busy" />
      <FormControl v-else v-model="year" class="billing-period" type="select" aria-label="Year" :options="years" :disabled="busy" />
      <span v-if="updated" class="billing-updated">Updated {{ updated }}</span>
      <Button variant="outline" label="Refresh" icon-left="refresh-cw" :loading="busy" :disabled="!account" @click="run(refresh)" />
    </header>
    <ErrorMessage :message="error" /><p v-if="notice" role="status" class="workspace-success">{{ notice }}</p>
    <p v-if="!account" class="billing-empty">Set the Hub account in Settings to see WhatsApp billing.</p>
    <LoadingRows v-else-if="!loaded && busy" label="Loading billing…" :count="4" />
    <template v-else-if="loaded">
      <p v-if="bills.length > 1" class="billing-sub">{{ bills.length }} WhatsApp numbers · {{ periodLabel }}</p>
      <div class="billing-cards">
        <div v-for="card in cards" :key="card.label" class="workflow-card billing-stat" :class="{ 'is-accent': card.accent }">
          <span>{{ card.label }}</span><strong>{{ card.value }}</strong><small>{{ card.note }}</small>
        </div>
      </div>

      <section v-for="bill in bills" :key="bill.channel" class="workflow-card billing-number" :aria-label="`${bill.label} bill`">
        <header class="billing-number-head">
          <span class="billing-number-icon" aria-hidden="true"><FeatherIcon name="message-circle" :size="16" /></span>
          <div class="billing-number-name"><strong>{{ bill.label }}<span v-if="bill.address" class="billing-wide"> · {{ bill.address }}</span></strong>
            <small><span v-if="bill.waba_id" class="billing-wide">WABA {{ bill.waba_id }}</span><span class="billing-narrow">{{ bill.address }}</span></small></div>
          <div class="billing-number-amount"><strong>{{ money(bill.statement.amount) }}</strong><small>{{ formatCount(bill.statement.messages) }} messages</small></div>
        </header>
        <p v-if="!bill.lines.length" class="billing-empty billing-number-empty">No messages in {{ periodLabel }}.</p>
        <div v-else class="billing-table-wrap" tabindex="0">
          <table class="billing-table">
            <thead><tr><th scope="col">Category</th><th scope="col" class="num">Messages</th><th scope="col" class="num">Rate</th><th scope="col" class="num">Amount</th></tr></thead>
            <tbody>
              <tr v-for="line in bill.lines" :key="line.category">
                <th scope="row"><span class="billing-category"><i :style="{ background: categoryColor(line.category) }" />{{ line.label }}</span></th>
                <td class="num">{{ formatCount(line.messages) }}</td>
                <td class="num" :class="{ 'is-free': line.free }">{{ line.free ? 'Free' : formatRate(line.rate, currency) }}</td><td class="num">{{ money(line.amount) }}</td>
              </tr>
            </tbody>
            <tfoot><tr><th scope="row">Total</th><td class="num">{{ formatCount(bill.statement.messages) }}</td><td class="num" /><td class="num">{{ money(bill.statement.amount) }}</td></tr></tfoot>
          </table>
        </div>
      </section>

      <section v-if="view === 'month' && !bills.length" class="workflow-card billing-panel" aria-labelledby="billing-statement-title">
        <h3 id="billing-statement-title">Statement · {{ periodLabel }}</h3>
        <p v-if="!lines.length" class="billing-empty">No WhatsApp messages in {{ periodLabel }}.</p>
        <div v-else class="billing-table-wrap" tabindex="0">
          <table class="billing-table">
            <thead><tr><th scope="col">Category</th><th scope="col" class="num">Messages</th><th scope="col" class="num">Rate per message</th><th scope="col" class="num">Amount</th></tr></thead>
            <tbody>
              <tr v-for="line in lines" :key="line.category">
                <th scope="row">{{ line.label }}</th><td class="num">{{ formatCount(line.messages) }}</td>
                <td class="num">{{ line.free ? 'Free' : formatRate(line.rate, currency) }}</td><td class="num">{{ money(line.amount) }}</td>
              </tr>
            </tbody>
            <tfoot><tr><th scope="row">Total</th><td class="num">{{ formatCount(statement.messages) }}</td><td class="num" /><td class="num">{{ money(statement.amount) }}</td></tr></tfoot>
          </table>
        </div>
      </section>

      <template v-if="view === 'year'">
        <section class="workflow-card billing-panel" aria-labelledby="billing-chart-title">
          <h3 id="billing-chart-title">Amount per month · {{ year }}</h3>
          <div class="billing-chart" role="img" :aria-label="bars.map(bar => `${bar.label} ${money(bar.amount)}`).join(', ')">
            <div v-for="bar in bars" :key="bar.label" class="billing-bar" :title="`${bar.label}: ${money(bar.amount)}`">
              <span class="billing-bar-fill" :style="{ height: bar.height + '%' }" /><small>{{ bar.label }}</small>
            </div>
          </div>
        </section>
        <section class="workflow-card billing-panel" aria-labelledby="billing-months-title">
          <h3 id="billing-months-title">Statement · {{ year }}</h3>
          <div class="billing-table-wrap" tabindex="0">
            <table class="billing-table">
              <thead><tr><th scope="col">Month</th><th scope="col" class="num">Messages</th><th scope="col" class="num">Amount</th></tr></thead>
              <tbody>
                <tr v-for="row in yearly" :key="row.period" :class="{ 'is-empty': !row.messages }">
                  <th scope="row">{{ row.label }}</th><td class="num">{{ formatCount(row.messages) }}</td><td class="num">{{ money(row.amount) }}</td>
                </tr>
              </tbody>
              <tfoot><tr><th scope="row">Total</th><td class="num">{{ formatCount(statement.messages) }}</td><td class="num">{{ money(statement.amount) }}</td></tr></tfoot>
            </table>
          </div>
        </section>
      </template>

      <section class="workflow-card billing-panel" aria-labelledby="billing-templates-title">
        <h3 id="billing-templates-title">By template</h3>
        <p v-if="!templates.length" class="billing-empty">No template messages in {{ periodLabel }}.</p>
        <div v-else class="billing-table-wrap" tabindex="0">
          <table class="billing-table">
            <thead><tr><th scope="col">Template</th><th scope="col">Category</th><th scope="col" class="num">Messages</th></tr></thead>
            <tbody>
              <tr v-for="row in templates" :key="row.template">
                <th scope="row">{{ row.template }}</th><td>{{ sentenceCase(row.category) }}</td><td class="num">{{ formatCount(row.messages) }}</td>
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
.billing-toolbar { display:flex; flex-wrap:wrap; align-items:center; gap:10px 12px; }
.billing-period { width:140px; }
.billing-toggle { display:inline-flex; padding:3px; border:1px solid var(--relay-stroke); border-radius:7px; background:var(--relay-hover); }
.billing-toggle button { position:relative; height:26px; min-height:26px; padding:0 14px; border-radius:5px; font-size:12.5px; color:var(--relay-ink-2); }
.billing-toggle button[aria-pressed=true] { background:var(--relay-layer-strong); color:var(--relay-ink); font-weight:600; box-shadow:var(--relay-shadow-1); }
.billing-updated { margin-left:auto; font-size:12px; color:var(--ink-gray-5); }
.billing-sub { margin-top:-6px; font-size:12.5px; color:var(--ink-gray-5); }
.billing-cards { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }
.billing-stat { gap:4px !important; padding:14px 16px !important; }
.billing-stat span { font-size:12px; color:var(--relay-ink-3); }
.billing-stat strong { font-size:22px; font-weight:600; letter-spacing:-.01em; color:var(--ink-gray-9); font-variant-numeric:tabular-nums; }
.billing-stat small { font-size:11.5px; color:var(--relay-ink-3); }
.billing-stat.is-accent { background:var(--relay-accent) !important; border-color:transparent !important; }
.billing-stat.is-accent :is(span,strong,small) { color:var(--relay-accent-ink); }
.billing-stat.is-accent :is(span,small) { opacity:.85; }
.billing-number { flex:none; gap:0 !important; padding:0 !important; overflow:hidden; min-width:0; }
.billing-number-head { display:flex; align-items:center; gap:12px; padding:12px 16px; border-bottom:1px solid var(--relay-stroke); }
.billing-number-icon { display:grid; place-items:center; flex:none; width:34px; height:34px; border-radius:8px; background:color-mix(in srgb,#25a35a 14%,transparent); color:#25a35a; }
.billing-number-name { min-width:0; flex:1; }
.billing-number-name strong, .billing-number-amount strong { display:block; font-size:14px; font-weight:600; color:var(--ink-gray-9); }
.billing-number-name small, .billing-number-amount small { display:block; margin-top:1px; font-size:12px; color:var(--relay-ink-3); }
.billing-number-amount { flex:none; text-align:right; font-variant-numeric:tabular-nums; }
.billing-number-amount strong { font-size:16px; }
.billing-narrow { display:none; }
.billing-number .billing-table-wrap { border:0; border-radius:0; }
.billing-number .billing-table thead th { background:var(--relay-hover); }
.billing-number .billing-table :is(th,td) { padding:9px 16px; }
.billing-number .billing-table { table-layout:fixed; }
.billing-number .billing-table th:first-child { width:40%; }
.billing-number .billing-table tfoot :is(th,td) { background:transparent; }
.billing-number-empty { padding:12px 16px; }
.billing-category { display:inline-flex; align-items:center; gap:8px; }
.billing-category i { display:inline-block; width:8px; height:8px; border-radius:2px; }
.billing-table .is-free { color:var(--relay-green); font-weight:600; }
.billing-panel { gap:12px !important; padding:16px !important; min-width:0; }
.billing-panel h3 { font-size:14px; }
.billing-chart { display:grid; grid-template-columns:repeat(12,minmax(0,1fr)); align-items:end; gap:8px; height:160px; }
.billing-bar { display:flex; flex-direction:column; align-items:center; justify-content:flex-end; gap:6px; height:100%; min-width:0; }
.billing-bar-fill { width:100%; max-width:36px; min-height:2px; border-radius:4px 4px 0 0; background:var(--relay-accent); transition:height var(--relay-normal) var(--relay-ease); }
.billing-bar small { font-size:11px; color:var(--ink-gray-5); }
.billing-table-wrap { overflow-x:auto; min-width:0; border:1px solid var(--relay-stroke); border-radius:var(--relay-radius); }
.billing-table { width:100%; border-collapse:collapse; font-size:13px; font-variant-numeric:tabular-nums; }
.billing-table :is(th,td) { padding:9px 12px; text-align:left; white-space:nowrap; border-bottom:1px solid var(--relay-stroke); }
.billing-table thead th { font-size:12px; font-weight:600; color:var(--ink-gray-5); background:var(--relay-layer); }
.billing-table tbody th { font-weight:500; color:var(--ink-gray-8); }
.billing-table tbody tr:hover { background:var(--relay-hover); }
.billing-table tr.is-empty :is(th,td) { color:var(--ink-gray-4); }
.billing-table tfoot :is(th,td) { font-weight:600; color:var(--ink-gray-9); border-bottom:0; background:var(--relay-layer); }
.billing-table .num { text-align:right; }
.billing-empty { font-size:13px; color:var(--ink-gray-5); }
@media (max-width:768px) {
  .billing-toggle button { height:28px; min-height:28px; font-size:13px; }
  .billing-toggle button::before { content:""; position:absolute; left:0; right:0; top:calc(50% - 20px); height:40px; }
  .billing-cards { grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }
  .billing-stat { padding:11px 12px !important; min-width:0; }
  .billing-stat.is-accent { order:-1; grid-column:1 / -1; }
  .billing-stat span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .billing-stat:not(.is-accent) small { display:none; }
  .billing-number-head { padding:10px 12px; }
  .billing-number .billing-table :is(th,td) { padding:8px 10px; }
  .billing-number .billing-table { table-layout:auto; }
  .billing-number .billing-table th:first-child { width:auto; }
  .billing-wide { display:none; }
  .billing-narrow { display:inline; }
  .billing-toolbar { display:grid; grid-template-columns:auto minmax(0,1fr); }
  .billing-period { width:auto; }
  .billing-updated { margin-left:0; }
  .billing-toolbar > :last-child { justify-self:end; }
  .billing-stat strong { font-size:18px; }
  .billing-stat:not(.is-accent) strong { font-size:16px; }
  .billing-chart { gap:4px; height:120px; }
  .billing-bar small { font-size:10px; }
  .billing-table :is(th,td) { padding:8px 6px; }
  .billing-table :is(thead th,tbody th) { white-space:normal; overflow-wrap:normal; word-break:normal; }
}
</style>
