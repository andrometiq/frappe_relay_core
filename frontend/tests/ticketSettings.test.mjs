import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { COLOURS, assigneeChartRows, readTicketRoute, ticketFilterRoute, ticketFiltersFromRoute, ticketRoute, chartRows, emptySettings, isClosed, movedNames, pickerOptions, removalHint, statusLook } from '../src/services/ticketSettings.js'

const settings = { ...emptySettings(), statuses: [
  { name: 'Open', label: 'Open', colour: 'amber', state: 'Open' }, { name: 'Started', label: 'Started', colour: 'red', state: 'Open' },
  { name: 'Done', label: 'Done', colour: 'green', state: 'Closed' }] }

test('a ticket takes its badge label and colour from its status', () => {
  assert.deepEqual(statusLook(settings, { ticket_status: 'Started' }), { label: 'Started', theme: 'red' })
  assert.deepEqual(statusLook(settings, { ticket_status: 'Gone' }), { label: 'Gone', theme: 'gray' })
})

test('a ticket is closed when its status is of type Closed', () => {
  assert.equal(isClosed(settings, { ticket_status: 'Done' }), true)
  assert.equal(isClosed(settings, { ticket_status: 'Started' }), false)
  assert.equal(isClosed(settings, null), false)
})

test('pickers list values in order with an optional first entry', () => {
  assert.deepEqual(pickerOptions(settings.statuses).map(row => row.value), ['Open', 'Started', 'Done'])
  assert.deepEqual(pickerOptions(settings.statuses, 'All')[0], { value: '', label: 'All' })
})

test('moving a row gives the new order and refuses to move past either end', () => {
  const rows = [{ name: 'a' }, { name: 'b' }, { name: 'c' }]
  assert.deepEqual(movedNames(rows, 0, 1), ['b', 'a', 'c'])
  assert.deepEqual(movedNames(rows, 2, -1), ['a', 'c', 'b'])
  assert.equal(movedNames(rows, 0, -1), null)
  assert.equal(movedNames(rows, 2, 1), null)
})

test('a value that tickets use says it cannot be deleted', () => {
  assert.equal(removalHint({ tickets: 0 }), '')
  assert.match(removalHint({ tickets: 1 }), /1 ticket use this, so it cannot be deleted/)
})

test('chart bars scale to the largest count and name empty values', () => {
  const rows = chartRows([{ assigned_to: 'a@x.invalid', tickets: 8 }, { assigned_to: null, tickets: 2 }], 'assigned_to', user => user || 'Unassigned')
  assert.deepEqual(rows, [{ key: 'a@x.invalid', label: 'a@x.invalid', tickets: 8, width: 100 }, { key: '', label: 'Unassigned', tickets: 2, width: 25 }])
})

test('colours are the badge themes the UI kit supports', () => {
  const badge = readFileSync(new URL('../src/ui/RelayBadge.vue', import.meta.url), 'utf8')
  for (const colour of COLOURS) assert.ok(badge.includes(colour + ': '), colour)
})

test('ticket screens read statuses and types from the settings API, not from lists in the code', () => {
  for (const file of ['components/TicketsWorkspace.vue', 'components/messages/CreateTicketDialog.vue']) {
    const source = readFileSync(new URL('../src/' + file, import.meta.url), 'utf8')
    assert.ok(!/Payment evidence|'In progress', 'Resolved'/.test(source), file)
  }
})

test('the shared settings store owns the realtime reload, and the create dialog reconciles its choices', () => {
  const store = readFileSync(new URL('../src/composables/useTicketSettings.js', import.meta.url), 'utf8')
  assert.match(store, /watchRealtime\(\['Relay Ticket'\], \['tickets'\]/)
  const workspace = readFileSync(new URL('../src/components/TicketsWorkspace.vue', import.meta.url), 'utf8')
  assert.ok(!/loadSettings\(true\)/.test(workspace))
  const dialog = readFileSync(new URL('../src/components/messages/CreateTicketDialog.vue', import.meta.url), 'utf8')
  assert.match(dialog, /loadSettings\(\)\.then\(reconcile/)
  assert.match(dialog, /watch\(settings, \(\) => \{ if \(open\.value\) reconcile\(\) \}\)/)
})

test('only the newest settings read or apply writes the shared store', async () => {
  const { register } = await import('node:module')
  const stub = source => 'data:text/javascript,' + encodeURIComponent(source)
  const stubs = {
    '../services/coreApi': stub('export const coreApi = () => globalThis.ticketSettingsRead()'),
    './useRealtimeRefresh': stub('export const watchRealtime = () => () => {}'),
  }
  register(stub(`const stubs = ${JSON.stringify(stubs)}
export async function resolve(specifier, context, next) {
  if (context.parentURL?.includes('/src/') && stubs[specifier]) return { url: stubs[specifier], shortCircuit: true }
  if (context.parentURL?.includes('/src/') && /^\\.\\.?\\//.test(specifier) && !/\\.\\w+$/.test(specifier)) return next(specifier + '.js', context)
  return next(specifier, context)
}`))
  const pending = []
  globalThis.ticketSettingsRead = () => new Promise(resolve => pending.push(resolve))
  const { useTicketSettings } = await import('../src/composables/useTicketSettings.js')
  const { settings, load, apply } = useTicketSettings()

  const first = load(), second = load(true)
  pending[1]({ types: ['Renamed'] }); await second
  pending[0]({ types: ['Old'] }); await first
  assert.deepEqual(settings.value.types, ['Renamed'])
  await load()
  assert.deepEqual(settings.value.types, ['Renamed'])

  const third = load(true)
  apply({ types: ['Saved'] })
  pending[2]({ types: ['Renamed'] }); await third
  assert.deepEqual(settings.value.types, ['Saved'])
})


test('assignee chart keeps the top eight open-ticket owners on one line and totals the rest', () => {
  const counts = Array.from({ length: 11 }, (_, index) => ({ assigned_to: index === 10 ? null : `user${index}@example.invalid`, tickets: 11 - index }))
  const rows = assigneeChartRows(counts.reverse(), user => user?.startsWith('user') ? 'Same name' : 'Unassigned')
  assert.equal(rows.length, 9)
  assert.equal(rows[0].label, 'Same name')
  assert.equal(rows[0].title, 'Same name (user0@example.invalid)')
  assert.equal(rows[8].label, 'Others')
  assert.equal(rows[8].tickets, 6)
  assert.equal(rows.reduce((sum, row) => sum + row.tickets, 0), 66)
  for (const row of rows) {
    assert.equal(row.filters.state, 'Open')
    const filters = ticketFiltersFromRoute(ticketFilterRoute(row.filters))
    for (const [field, value] of Object.entries(row.filters)) assert.equal(filters[field], value)
  }
  assert.deepEqual(JSON.parse(rows[8].filters.exclude_assignees), Array.from({ length: 8 }, (_, index) => `user${index}@example.invalid`))
  assert.equal(assigneeChartRows(counts.slice(0, 2), user => user || 'Unassigned').length, 2)
  assert.deepEqual(assigneeChartRows([], user => user), [])
})

test('the Tickets URL holds the view, every list filter and the open ticket', () => {
  assert.equal(ticketRoute(), '#/tickets')
  assert.equal(ticketRoute({ view: 'settings' }), '#/tickets?view=settings')
  assert.equal(ticketRoute({ view: 'dashboard', ticket: 'TKT-1' }), '#/tickets?view=dashboard&ticket=TKT-1')
  const filters = { query: 'late parcel', ticket_status: 'Open', mine: 1, state: 'Open', assigned: 1, business_type: 'Customer' }
  const route = ticketRoute({ view: 'tickets', filters, ticket: 'TKT-2' })
  assert.deepEqual(readTicketRoute(route), { view: 'tickets', ticket: 'TKT-2', filters: { ...filters, assigned: '1' } })
  assert.equal(ticketRoute({ view: 'tickets', filters: { query: '', ticket_status: '', mine: 0 } }), '#/tickets?view=tickets')
  assert.equal(ticketRoute({ view: 'dashboard', filters }), '#/tickets')
})

test('a bare ticket link opens over the list and unknown views fall back to the dashboard', () => {
  assert.equal(readTicketRoute('#/tickets?ticket=TKT-3').view, 'tickets')
  assert.equal(readTicketRoute('#/tickets?view=other').view, 'dashboard')
  assert.equal(readTicketRoute('#/tickets').view, 'dashboard')
})

test('empty assignee and type filters survive navigation and differ from all tickets', () => {
  const unassigned = ticketFiltersFromRoute(ticketFilterRoute({ assigned_to: '' }))
  const noType = ticketFiltersFromRoute(ticketFilterRoute({ ticket_type: '' }))
  assert.equal(unassigned.assigned_to, '')
  assert.equal(noType.ticket_type, '')
  assert.equal(ticketFiltersFromRoute('#/tickets').assigned_to, undefined)
  assert.equal(ticketFiltersFromRoute(ticketFilterRoute({ ticket_type: 'Orders & returns' })).ticket_type, 'Orders & returns')
})


test('legacy amber colours render without rewriting saved settings', () => {
  assert.deepEqual(statusLook(settings, { ticket_status: 'Open' }), { label: 'Open', theme: 'blue' })
  const legacy = { statuses: [{ name: 'Archived', label: 'Archived', colour: 'amber', state: 'Closed' }] }
  assert.equal(statusLook(legacy, { ticket_status: 'Archived' }).theme, 'gray')
  assert.equal(settings.statuses[0].colour, 'amber')
  const pending = { statuses: [{ name: 'Pending', label: 'Pending', colour: 'amber', state: 'Open' }] }
  assert.equal(statusLook(pending, { ticket_status: 'Pending' }).theme, 'gray')
})
