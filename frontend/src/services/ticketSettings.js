export const COLOURS = ['gray', 'blue', 'green', 'amber', 'red']

export const emptySettings = () => ({ can_manage: false, status_types: [], statuses: [], types: [] })

// Label and badge colour of a ticket's status.
export function statusLook(settings, ticket) {
  const status = settings.statuses.find(row => row.name === ticket.ticket_status)
  return { label: status?.label || ticket.ticket_status || 'No status', theme: status?.colour || 'gray' }
}

export function isClosed(settings, ticket) {
  return settings.statuses.find(row => row.name === ticket?.ticket_status)?.state === 'Closed'
}

// Picker options in sort order, with an optional first entry for "no value".
export function pickerOptions(rows, emptyLabel = '') {
  const options = rows.map(row => ({ value: row.name, label: row.label }))
  return emptyLabel ? [{ value: '', label: emptyLabel }, ...options] : options
}

// The new name order after moving one row up (-1) or down (+1); null when it cannot move.
export function movedNames(rows, index, step) {
  const target = index + step
  if (target < 0 || target >= rows.length) return null
  const names = rows.map(row => row.name)
  names.splice(target, 0, names.splice(index, 1)[0])
  return names
}

export function removalHint(row) {
  return row.tickets ? `${row.tickets} ticket${row.tickets === 1 ? '' : 's'} use this, so it cannot be deleted.` : ''
}

export const emptyTicketFilters = () => ({ query: '', ticket_status: '', mine: 0 })

// Open and closed totals from the per-status counts, by the type of each status.
export function ticketTotals(settings, rows) {
  const totals = { open: 0, closed: 0 }
  for (const row of rows) totals[isClosed(settings, row) ? 'closed' : 'open'] += row.tickets
  return totals
}

// Bar rows for one count list: each bar's width is its share of the largest count.
export function chartRows(rows, field, label) {
  const largest = Math.max(1, ...rows.map(row => row.tickets))
  return rows.map(row => ({ key: row[field] || '', label: label(row[field]), tickets: row.tickets, width: Math.round(row.tickets / largest * 100) }))
}

// Keep every count represented; Others filters out the eight visible assignees.
export function assigneeChartRows(rows, label) {
  const sorted = [...rows].sort((a, b) => b.tickets - a.tickets)
  const visible = sorted.slice(0, 8)
  const labels = visible.map(row => label(row.assigned_to))
  const result = chartRows(visible, 'assigned_to', user => {
    const name = label(user)
    return user && labels.filter(value => value === name).length > 1 ? `${name} (${user})` : name
  }).map(row => ({ ...row, filters: { assigned_to: row.key } }))
  if (sorted.length > 8) result.push({ key: 'others', label: 'Others',
    tickets: sorted.slice(8).reduce((sum, row) => sum + row.tickets, 0),
    filters: { exclude_assignees: JSON.stringify(visible.map(row => row.assigned_to || '')) } })
  const largest = Math.max(1, ...result.map(row => row.tickets))
  return result.map(row => ({ ...row, width: Math.round(row.tickets / largest * 100) }))
}

export function ticketFilterRoute(filters) {
  return '#/tickets?' + new URLSearchParams({ view: 'tickets', ...filters }).toString()
}

export function ticketFiltersFromRoute(hash) {
  const params = new URLSearchParams(hash.split('?')[1] || '')
  const filters = emptyTicketFilters()
  for (const field of ['assigned_to', 'ticket_type', 'exclude_assignees']) {
    if (params.has(field)) filters[field] = params.get(field)
  }
  return filters
}
