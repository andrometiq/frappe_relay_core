// View helpers for the WhatsApp Billing tab over relay_core.billing.get_billing.
export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

export function formatCount(value) {
  return new Intl.NumberFormat('en-IN').format(Number(value) || 0)
}

function formatNumber(value, currency, maximumFractionDigits) {
  const options = { minimumFractionDigits: 2, maximumFractionDigits }
  if (currency) Object.assign(options, { style: 'currency', currency })
  return new Intl.NumberFormat('en-IN', options).format(Number(value) || 0)
}

// INR shows as ₹ with en-IN grouping; a missing currency shows the plain amount.
export function formatMoney(value, currency) {
  return formatNumber(value, currency, 2)
}

// A rate per message keeps up to 4 decimals, so ₹0.1495 does not read as ₹0.15.
export function formatRate(value, currency) {
  return formatNumber(value, currency, 4)
}

// "2026-10-26 21:18:38.236646" from the server, read as site time without a timezone shift.
export function formatFetched(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(value || '')
  if (!match) return ''
  const [, year, month, day, hour, minute] = match
  const clock = `${Number(hour) % 12 || 12}:${minute} ${Number(hour) < 12 ? 'am' : 'pm'}`
  return `${Number(day)} ${MONTHS[Number(month) - 1]} ${year}, ${clock}`
}

export function monthName(period) {
  const [year, month] = String(period).split('-')
  return `${MONTH_NAMES[Number(month) - 1]} ${year}`
}

export function categoryLabel(category) {
  if (category === 'SERVICE') return 'Service / free'
  return String(category || 'Other').toLowerCase().replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase())
}

// The last 24 months, newest first, as "2026-10" values.
export function monthOptions(today = new Date()) {
  return Array.from({ length: 24 }, (_, offset) => {
    const day = new Date(today.getFullYear(), today.getMonth() - offset, 1)
    const value = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}`
    return { value, label: `${MONTHS[day.getMonth()]} ${day.getFullYear()}` }
  })
}

export function yearOptions(today = new Date()) {
  const year = today.getFullYear()
  return [0, 1, 2, 3].map(offset => String(year - offset))
}

export function statementLines(lines) {
  return (lines || []).map(line => ({ ...line, label: categoryLabel(line.category), free: line.category === 'SERVICE' }))
}

// Messages, amount and, when some messages were charged, the average charge per charged message.
export function summaryCards(statement, periodLabel, currency) {
  const paid = (statement?.lines || []).filter(line => line.category !== 'SERVICE' && line.amount)
  const paidMessages = paid.reduce((sum, line) => sum + line.messages, 0)
  const cards = [
    { label: 'Messages sent', value: formatCount(statement?.messages) },
    { label: `Amount for ${periodLabel}`, value: formatMoney(statement?.amount, currency), accent: true },
  ]
  if (paidMessages) cards.push({ label: 'Average per charged message', value: formatRate(statement.amount / paidMessages, currency) })
  return cards
}

export function yearRows(months) {
  return (months || []).map(month => ({ label: MONTHS[Number(month.period.slice(5, 7)) - 1], period: month.period,
    messages: month.messages, amount: month.amount }))
}

// Bar heights as a percent of the largest monthly amount; an empty year draws no bars.
export function chartBars(rows) {
  const highest = Math.max(0, ...rows.map(row => row.amount))
  return rows.map(row => ({ label: row.label, amount: row.amount, height: highest ? Math.round((100 * row.amount) / highest) : 0 }))
}

// Template message counts for one "2026-10" month, or the whole year without one; busiest first.
export function templateRows(templates, month = '') {
  const rows = new Map()
  for (const item of templates || []) {
    if (month && !item.period.startsWith(month)) continue
    const row = rows.get(item.template) || { template: item.template, category: item.category ? categoryLabel(item.category) : '—', messages: 0 }
    row.messages += item.messages
    rows.set(item.template, row)
  }
  return [...rows.values()].sort((left, right) => right.messages - left.messages || left.template.localeCompare(right.template))
}
