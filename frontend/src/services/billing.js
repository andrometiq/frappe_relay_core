// View helpers for the WhatsApp Billing tab over relay_core.billing.get_billing.
export const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const CATEGORIES = ['marketing', 'utility', 'authentication']

export function formatCount(value) {
  return new Intl.NumberFormat('en-IN').format(Number(value) || 0)
}

// INR shows as ₹ with en-IN grouping; a missing currency shows the plain amount.
export function formatMoney(value, currency) {
  const options = { minimumFractionDigits: 2, maximumFractionDigits: 2 }
  if (!currency) return new Intl.NumberFormat('en-IN', options).format(Number(value) || 0)
  return new Intl.NumberFormat('en-IN', { ...options, style: 'currency', currency }).format(Number(value) || 0)
}

export function formatPercent(value) {
  return `${new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(Number(value) || 0)}%`
}

// "2026-10-26 21:18:38.236646" from the server, read as site time without a timezone shift.
export function formatFetched(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(value || '')
  if (!match) return 'Never'
  const [, year, month, day, hour, minute] = match
  const clock = `${Number(hour) % 12 || 12}:${minute} ${Number(hour) < 12 ? 'am' : 'pm'}`
  return `${Number(day)} ${MONTHS[Number(month) - 1]} ${year}, ${clock}`
}

export function monthLabel(period) {
  return MONTHS[Number(String(period).slice(5, 7)) - 1] || ''
}

// Free messages (customer service window, free entry points) go to "Service free"; paid ones to their category.
export function categoryColumn(row) {
  if (/^FREE/.test(row.pricing_type) || row.category === 'SERVICE') return 'service_free'
  return CATEGORIES.find(name => row.category.toLowerCase().startsWith(name)) || 'other'
}

export function monthRows(months) {
  return (months || []).map(month => {
    const columns = { marketing: 0, utility: 0, authentication: 0, service_free: 0, other: 0 }
    for (const row of month.categories) columns[categoryColumn(row)] += row.volume
    return { label: monthLabel(month.period), period: month.period, messages: month.volume, messages_sent: month.messages_sent,
      ...columns, meta_cost: month.meta_cost, margin_amount: month.margin_amount, total: month.total }
  })
}

export function categoryLabel(category) {
  return String(category || 'Unknown').toLowerCase().replaceAll('_', ' ').replace(/^./, letter => letter.toUpperCase())
}

// Yearly per-category totals with each category's share of the year's Meta charge.
export function categoryRows(categories, total) {
  return (categories || []).map(row => ({ ...row, label: categoryLabel(row.category),
    share: total?.meta_cost ? Math.round((1000 * row.meta_cost) / total.meta_cost) / 10 : 0 }))
}

export function summaryCards(data) {
  const total = data?.total || {}, currency = data?.currency
  return [
    { label: 'Messages sent', value: formatCount(total.volume), hint: `${formatCount(total.messages_sent)} sent from Relay` },
    { label: 'Meta charges', value: formatMoney(total.meta_cost, currency), hint: 'Charged by Meta' },
    { label: 'Margin', value: formatMoney(total.margin_amount, currency), hint: `${formatPercent(data?.margin_percent)} of Meta charges` },
    { label: 'Total to bill', value: formatMoney(total.total, currency), hint: 'Meta charges plus margin', accent: true },
  ]
}

// One row per template with its 12 monthly counts and the year total, busiest first.
export function templateRows(templates) {
  const rows = new Map()
  for (const item of templates || []) {
    const row = rows.get(item.template) || { template: item.template, category: item.category, months: Array(12).fill(0), total: 0 }
    row.months[Number(item.period.slice(5, 7)) - 1] += item.messages_sent
    row.total += item.messages_sent
    rows.set(item.template, row)
  }
  return [...rows.values()].sort((left, right) => right.total - left.total || left.template.localeCompare(right.template))
}

// Bar heights as a percent of the busiest month; an empty year draws no bars.
export function chartBars(rows) {
  const highest = Math.max(0, ...rows.map(row => row.total))
  return rows.map(row => ({ label: row.label, total: row.total, height: highest ? Math.round((100 * row.total) / highest) : 0 }))
}

export function yearOptions(today = new Date()) {
  const year = today.getFullYear()
  return [0, 1, 2, 3].map(offset => String(year - offset))
}
