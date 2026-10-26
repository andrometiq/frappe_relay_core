import test from 'node:test'
import assert from 'node:assert/strict'
import {
  categoryColumn, categoryRows, chartBars, formatCount, formatFetched, formatMoney, formatPercent, monthRows, summaryCards, templateRows, yearOptions,
} from '../src/services/billing.js'

const priced = (volume, meta_cost, margin = 30) => {
  const margin_amount = Math.round(meta_cost * margin * 100) / 10000
  return { volume, meta_cost, margin_amount, total: meta_cost + margin_amount }
}
const month = (period, categories, messages_sent = 0) => {
  const volume = categories.reduce((sum, row) => sum + row.volume, 0)
  const meta_cost = categories.reduce((sum, row) => sum + row.meta_cost, 0)
  return { period, messages_sent, categories, ...priced(volume, meta_cost) }
}
const billing = {
  year: 2026, currency: 'INR', margin_percent: 30, fetched_at: '2026-10-26 21:18:38.236646',
  months: [
    month('2026-02-01', [{ category: 'MARKETING', pricing_type: 'REGULAR', ...priced(9, 7.7679) },
      { category: 'SERVICE', pricing_type: 'FREE_CUSTOMER_SERVICE', ...priced(20, 0) }]),
    month('2026-03-01', [{ category: 'UTILITY', pricing_type: 'REGULAR', ...priced(1231, 141.565) },
      { category: 'UTILITY', pricing_type: 'FREE_CUSTOMER_SERVICE', ...priced(17, 0) },
      { category: 'AUTHENTICATION', pricing_type: 'REGULAR', ...priced(4, 0.5) }], 55),
  ],
  categories: [{ category: 'MARKETING', ...priced(9, 7.7679) }, { category: 'SERVICE', ...priced(20, 0) }, { category: 'UTILITY', ...priced(1248, 142.065) }],
  total: { ...priced(1281, 149.8329), messages_sent: 1250 },
  templates: [
    { template: 'order_ready', category: 'UTILITY', period: '2026-03-01', messages_sent: 4 },
    { template: 'order_ready', category: 'UTILITY', period: '2026-09-01', messages_sent: 6 },
    { template: 'diwali_offer', category: 'MARKETING', period: '2026-09-01', messages_sent: 30 },
  ],
}

test('money uses the API currency with en-IN grouping', () => {
  assert.equal(formatMoney(151524.84, 'INR'), '₹1,51,524.84')
  assert.equal(formatMoney(0, 'INR'), '₹0.00')
  assert.equal(formatMoney(1234.5, ''), '1,234.50')
  assert.equal(formatCount(1234567), '12,34,567')
  assert.equal(formatCount(undefined), '0')
})

test('margin percent and last update read as plain text', () => {
  assert.equal(formatPercent(30), '30%')
  assert.equal(formatPercent(12.5), '12.5%')
  assert.equal(formatPercent(0), '0%')
  assert.equal(formatFetched('2026-10-26 21:18:38.236646'), '26 Oct 2026, 9:18 pm')
  assert.equal(formatFetched('2026-02-01 00:05:00'), '1 Feb 2026, 12:05 am')
  assert.equal(formatFetched(null), 'Never')
})

test('free messages count as Service free and paid ones go to their category', () => {
  assert.equal(categoryColumn({ category: 'UTILITY', pricing_type: 'FREE_CUSTOMER_SERVICE' }), 'service_free')
  assert.equal(categoryColumn({ category: 'SERVICE', pricing_type: 'REGULAR' }), 'service_free')
  assert.equal(categoryColumn({ category: 'MARKETING_LITE', pricing_type: 'REGULAR' }), 'marketing')
  assert.equal(categoryColumn({ category: 'AUTHENTICATION_INTERNATIONAL', pricing_type: 'REGULAR' }), 'authentication')
  const [february, march] = monthRows(billing.months)
  assert.deepEqual([february.label, february.messages, february.marketing, february.service_free], ['Feb', 29, 9, 20])
  assert.deepEqual([march.utility, march.service_free, march.authentication, march.messages_sent], [1231, 17, 4, 55])
  assert.equal(march.total, march.meta_cost + march.margin_amount)
})

test('summary cards show the year totals and the margin math', () => {
  const cards = summaryCards(billing)
  assert.deepEqual(cards.map(card => card.label), ['Messages sent', 'Meta charges', 'Margin', 'Total to bill'])
  assert.deepEqual(cards.map(card => card.value), ['1,281', '₹149.83', '₹44.95', '₹194.78'])
  assert.equal(cards[0].hint, '1,250 sent from Relay')
  assert.equal(cards[2].hint, '30% of Meta charges')
  assert.equal(summaryCards(null)[3].value, '0.00')
})

test('yearly categories carry their share of the Meta charge', () => {
  const rows = categoryRows(billing.categories, billing.total)
  assert.deepEqual(rows.map(row => [row.label, row.share]), [['Marketing', 5.2], ['Service', 0], ['Utility', 94.8]])
  assert.equal(categoryRows(billing.categories, { meta_cost: 0 })[0].share, 0)
})

test('templates pivot into monthly counts, busiest first', () => {
  const rows = templateRows(billing.templates)
  assert.deepEqual(rows.map(row => [row.template, row.total]), [['diwali_offer', 30], ['order_ready', 10]])
  assert.equal(rows[1].months[2], 4)
  assert.equal(rows[1].months[8], 6)
  assert.deepEqual(templateRows(undefined), [])
})

test('chart bars scale to the busiest month and an empty year draws none', () => {
  const bars = chartBars([{ label: 'Jan', total: 0 }, { label: 'Feb', total: 50 }, { label: 'Mar', total: 200 }])
  assert.deepEqual(bars.map(bar => bar.height), [0, 25, 100])
  assert.deepEqual(chartBars([{ label: 'Jan', total: 0 }]).map(bar => bar.height), [0])
  assert.deepEqual(yearOptions(new Date(2026, 9, 26)), ['2026', '2025', '2024', '2023'])
})
