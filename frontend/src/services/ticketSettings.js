export const COLOURS = ['gray', 'blue', 'green', 'amber', 'red']
const STATE_COLOURS = { Open: 'amber', 'In progress': 'blue', Resolved: 'green', Closed: 'gray' }

export const emptySettings = () => ({ can_manage: false, states: [], statuses: [], categories: [], types: [] })

// Label and badge colour of a ticket row; a ticket without a configured status falls back to its state.
export function statusLook(settings, ticket) {
  const status = settings.statuses.find(row => row.name === ticket.ticket_status)
  return { label: status?.label || ticket.status, theme: status?.colour || STATE_COLOURS[ticket.status] || 'gray' }
}

// Picker options: enabled values in sort order, plus the value a record already holds even when it is turned off.
export function pickerOptions(rows, current = '', allLabel = '') {
  const options = rows.filter(row => row.enabled || row.name === current).map(row => ({ value: row.name, label: row.label }))
  return allLabel ? [{ value: '', label: allLabel }, ...options] : options
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
  return row.tickets ? `${row.tickets} ticket${row.tickets === 1 ? '' : 's'} use this. Turn it off instead of deleting it.` : ''
}

export const emptyTicketFilters = () => ({ query: '', ticket_status: '', mine: '', category: '', ticket_type: '', business_doctype: '', business_name: '', assigned_to: '' })

// Filters kept behind the Filters button; each one set shows as a removable chip.
export const TICKET_PANEL_FILTERS = ['category', 'ticket_type', 'business_doctype', 'business_name', 'assigned_to']

export function activeTicketFilters(filters) {
  return TICKET_PANEL_FILTERS.filter(key => filters?.[key])
}
