import test from 'node:test'
import assert from 'node:assert/strict'
import {
  categoryColor, categoryLabel, chartBars, formatCount, numberBills, formatFetched, formatMoney, formatRate, monthName, monthOptions, statementLines, summaryCards, templateRows,
  yearOptions, yearRows,
} from '../src/services/billing.js'

const march = {
  period: '2026-03-01', messages: 1252, amount: 186.03,
  lines: [{ category: 'UTILITY', messages: 1231, rate: 0.1495, amount: 184.03 }, { category: 'AUTHENTICATION', messages: 4, rate: 0.5, amount: 2 },
    { category: 'SERVICE', messages: 17, rate: 0, amount: 0 }],
}
const templates = [
  { template: 'order_ready', category: 'UTILITY', period: '2026-03-01', messages: 4 },
  { template: 'order_ready', category: 'UTILITY', period: '2026-09-01', messages: 6 },
  { template: 'diwali_offer', category: 'MARKETING', period: '2026-09-01', messages: 30 },
  { template: 'old_template', category: '', period: '2026-09-01', messages: 1 },
]

test('money and rates use the API currency with en-IN grouping', () => {
  assert.equal(formatMoney(151524.84, 'INR'), '₹1,51,524.84')
  assert.equal(formatMoney(0, 'INR'), '₹0.00')
  assert.equal(formatMoney(1234.5, ''), '1,234.50')
  assert.equal(formatRate(0.1495, 'INR'), '₹0.1495')
  assert.equal(formatRate(0.5, 'INR'), '₹0.50')
  assert.equal(formatCount(1234567), '12,34,567')
  assert.equal(formatCount(undefined), '0')
})

test('periods and the last update read as plain text', () => {
  assert.equal(monthName('2026-10'), 'October 2026')
  assert.equal(monthName('2026-03-01'), 'March 2026')
  assert.equal(formatFetched('2026-10-26 21:18:38.236646'), '26 Oct 2026, 9:18 pm')
  assert.equal(formatFetched(null), '')
  const options = monthOptions(new Date(2026, 1, 15))
  assert.equal(options.length, 24)
  assert.deepEqual(options.slice(0, 3), [{ value: '2026-02', label: 'Feb 2026' }, { value: '2026-01', label: 'Jan 2026' },
    { value: '2025-12', label: 'Dec 2025' }])
  assert.deepEqual(yearOptions(new Date(2026, 9, 26)), ['2026', '2025', '2024', '2023'])
})

test('statement lines name categories and mark free messages', () => {
  const lines = statementLines(march.lines)
  assert.deepEqual(lines.map(line => [line.label, line.free]), [['Utility', false], ['Authentication', false], ['Service replies', true]])
  assert.equal(categoryLabel('MARKETING_LITE'), 'Marketing lite')
  assert.deepEqual(statementLines(undefined), [])
})

test('summary cards read like a phone bill and never show Meta cost or the service charge', () => {
  const cards = summaryCards(march, 'March 2026', 2, 'INR')
  assert.deepEqual(cards.map(card => [card.label, card.value, card.note]), [['Messages', '1,252', 'All 2 numbers'],
    ['Free replies', '17', 'Replies within 24 h'], ['Paid messages', '1,235', 'Marketing, utility, login codes'], ['Amount to pay', '₹186.03', 'March 2026']])
  assert.equal(cards.filter(card => card.accent).length, 1)
  assert.equal(summaryCards(march, 'March 2026', 1, 'INR')[0].note, 'All WhatsApp messages')
  assert.deepEqual(summaryCards(undefined, '2026', 0, 'INR').map(card => card.value), ['0', '0', '0', '₹0.00'])
  assert.doesNotMatch(JSON.stringify(cards), /meta|margin|service charge/i)
})

test('each number gets its own bill for the month or the year', () => {
  const sales = { channel: 'WA-1', label: 'Sales line', months: [march], total: { lines: [], messages: 1252, amount: 186.03 } }
  assert.equal(numberBills([sales], '2026-03')[0].statement, march)
  assert.deepEqual(numberBills([sales], '2026-04')[0].statement, { lines: [], messages: 0, amount: 0 })
  assert.equal(numberBills([sales])[0].statement, sales.total)
  assert.deepEqual(numberBills(undefined), [])
  assert.equal(categoryColor('MARKETING'), '#8a5cf6')
  assert.equal(categoryColor('MARKETING_LITE'), 'var(--relay-ink-4)')
})

test('the year shows months with amounts and bars scaled to the largest month', () => {
  const rows = yearRows([{ period: '2026-01-01', messages: 0, amount: 0 }, { period: '2026-02-01', messages: 9, amount: 50 }, march])
  assert.deepEqual(rows.map(row => [row.label, row.messages, row.amount]), [['Jan', 0, 0], ['Feb', 9, 50], ['Mar', 1252, 186.03]])
  assert.deepEqual(chartBars(rows).map(bar => bar.height), [0, 27, 100])
  assert.deepEqual(chartBars([{ label: 'Jan', amount: 0 }]).map(bar => bar.height), [0])
})

test('templates count for the chosen month or the whole year, busiest first', () => {
  assert.deepEqual(templateRows(templates, '2026-09').map(row => [row.template, row.category, row.messages]),
    [['diwali_offer', 'Marketing', 30], ['order_ready', 'Utility', 6], ['old_template', '—', 1]])
  assert.deepEqual(templateRows(templates).map(row => [row.template, row.messages]), [['diwali_offer', 30], ['order_ready', 10], ['old_template', 1]])
  assert.deepEqual(templateRows(templates, '2026-05'), [])
  assert.deepEqual(templateRows(undefined), [])
})
