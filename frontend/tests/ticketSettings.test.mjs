import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { COLOURS, chartRows, emptySettings, isClosed, movedNames, pickerOptions, removalHint, statusLook, ticketTotals } from '../src/services/ticketSettings.js'

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

test('dashboard totals count each status by its type', () => {
  const rows = [{ ticket_status: 'Open', tickets: 4 }, { ticket_status: 'Started', tickets: 2 }, { ticket_status: 'Done', tickets: 3 }]
  assert.deepEqual(ticketTotals(settings, rows), { open: 6, closed: 3 })
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
