export const COLOURS = ['gray', 'blue', 'green', 'amber', 'red']

export const emptySettings = () => ({ can_manage: false, status_types: [], statuses: [], types: [] })

// Keep saved colour identifiers valid; amber is blue for active work and grey otherwise.
export function ticketColour(row) {
  if (row?.colour !== 'amber') return row?.colour || 'gray'
  const neutral = ['closed', 'pending', 'unassigned'].includes((row.label || '').trim().toLowerCase())
  return row.state === 'Open' && !neutral ? 'blue' : 'gray'
}

// Label and badge colour of a ticket's status.
export function statusLook(settings, ticket) {
  const status = settings.statuses.find(row => row.name === ticket.ticket_status)
  return { label: status?.label || ticket.ticket_status || 'No status', theme: ticketColour(status) }
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

// Bar rows for one count list: each bar's width is its share of the largest count.
export function chartRows(rows, field, label) {
  const largest = Math.max(1, ...rows.map(row => row.tickets))
  return rows.map(row => ({ key: row[field] || '', label: label(row[field]), tickets: row.tickets, width: Math.round(row.tickets / largest * 100) }))
}

// Open tickets of the eight busiest assignees; Others filters out those eight.
export function assigneeChartRows(rows, label) {
  const sorted = [...rows].sort((a, b) => b.tickets - a.tickets)
  const visible = sorted.slice(0, 8)
  const result = chartRows(visible, 'assigned_to', label).map(row => ({ ...row,
    title: row.key ? `${row.label} (${row.key})` : row.label, filters: { state: 'Open', assigned_to: row.key } }))
  if (sorted.length > 8) result.push({ key: 'others', label: 'Others', title: 'Others',
    tickets: sorted.slice(8).reduce((sum, row) => sum + row.tickets, 0),
    filters: { state: 'Open', exclude_assignees: JSON.stringify(visible.map(row => row.assigned_to || '')) } })
  const largest = Math.max(1, ...result.map(row => row.tickets))
  return result.map(row => ({ ...row, width: Math.round(row.tickets / largest * 100) }))
}

const VIEWS = ['dashboard', 'tickets', 'settings']
const ROUTE_FILTERS = ['query', 'ticket_status', 'mine', 'state', 'assigned', 'resolved_today', 'assigned_to',
  'ticket_type', 'exclude_assignees', 'business_type', 'unlinked']
// An empty value of these is itself a filter: no owner, no type.
const EMPTY_FILTERS = ['assigned_to', 'ticket_type']

// The Tickets URL: the dashboard is #/tickets, the list carries its filters, and an open ticket is added on top.
export function ticketRoute({ view = 'dashboard', filters = {}, ticket = '' } = {}) {
  const params = new URLSearchParams()
  if (view !== 'dashboard' || ticket) params.set('view', view)
  if (view === 'tickets') {
    for (const key of ROUTE_FILTERS) {
      const value = filters[key]
      if ((value && value !== '0') || (value === '' && EMPTY_FILTERS.includes(key))) params.set(key, value)
    }
  }
  if (ticket) params.set('ticket', ticket)
  const query = params.toString()
  return '#/tickets' + (query ? '?' + query : '')
}

export function ticketFilterRoute(filters) {
  return ticketRoute({ view: 'tickets', filters })
}

// View, list filters and open ticket of a Tickets URL; a bare ticket link opens over the list.
export function readTicketRoute(hash) {
  const params = new URLSearchParams(hash.split('?')[1] || '')
  const ticket = params.get('ticket') || ''
  const view = VIEWS.includes(params.get('view')) ? params.get('view') : ticket ? 'tickets' : 'dashboard'
  return { view, ticket, filters: ticketFiltersFromRoute(hash) }
}

export function ticketFiltersFromRoute(hash) {
  const params = new URLSearchParams(hash.split('?')[1] || '')
  const filters = emptyTicketFilters()
  for (const field of ROUTE_FILTERS) {
    if (params.has(field)) filters[field] = params.get(field)
  }
  filters.mine = Number(filters.mine) ? 1 : 0
  return filters
}
