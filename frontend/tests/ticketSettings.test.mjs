import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { COLOURS, emptySettings, movedNames, pickerOptions, removalHint, statusLook } from '../src/services/ticketSettings.js'
import { ticketPayload } from '../src/services/ticketForm.js'

const settings = { ...emptySettings(), statuses: [
  { name: 'Open', label: 'Open', colour: 'amber', enabled: 1 }, { name: 'Started', label: 'Started', colour: 'red', enabled: 1 },
  { name: 'Old', label: 'Old', colour: 'gray', enabled: 0 }] }

test('a ticket takes its badge label and colour from its configured status', () => {
  assert.deepEqual(statusLook(settings, { ticket_status: 'Started', status: 'In progress' }), { label: 'Started', theme: 'red' })
})

test('a ticket without a configured status falls back to its state', () => {
  assert.deepEqual(statusLook(settings, { status: 'Resolved' }), { label: 'Resolved', theme: 'green' })
  assert.deepEqual(statusLook(settings, { ticket_status: 'Gone', status: 'Closed' }), { label: 'Closed', theme: 'gray' })
})

test('pickers list enabled values, the current value even when off, and an optional All entry', () => {
  assert.deepEqual(pickerOptions(settings.statuses).map(row => row.value), ['Open', 'Started'])
  assert.deepEqual(pickerOptions(settings.statuses, 'Old').map(row => row.value), ['Open', 'Started', 'Old'])
  assert.deepEqual(pickerOptions(settings.statuses, '', 'All tickets')[0], { value: '', label: 'All tickets' })
})

test('moving a row gives the new order and refuses to move past either end', () => {
  const rows = [{ name: 'a' }, { name: 'b' }, { name: 'c' }]
  assert.deepEqual(movedNames(rows, 0, 1), ['b', 'a', 'c'])
  assert.deepEqual(movedNames(rows, 2, -1), ['a', 'c', 'b'])
  assert.equal(movedNames(rows, 0, -1), null)
  assert.equal(movedNames(rows, 2, 1), null)
})

test('a value that tickets use says to turn it off', () => {
  assert.equal(removalHint({ tickets: 0 }), '')
  assert.match(removalHint({ tickets: 1 }), /1 ticket use this/)
})

test('colours are the badge themes the UI kit supports', () => {
  const badge = readFileSync(new URL('../src/ui/RelayBadge.vue', import.meta.url), 'utf8')
  for (const colour of COLOURS) assert.ok(badge.includes(colour + ': '), colour)
})

test('the ticket form sends the chosen category and type only when set', () => {
  const form = { subject: 'S', brief: '', priority: 'Low', assignedTo: '', tagged: [] }
  assert.equal('category' in ticketPayload(form, []), false)
  assert.deepEqual(ticketPayload({ ...form, category: 'Support', ticketType: 'General' }, []).ticket_type, 'General')
})

test('ticket screens read statuses, categories and types from the settings API, not from lists in the code', () => {
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
  pending[1]({ categories: ['Renamed'] }); await second
  pending[0]({ categories: ['Old'] }); await first
  assert.deepEqual(settings.value.categories, ['Renamed'])
  await load()
  assert.deepEqual(settings.value.categories, ['Renamed'])

  const third = load(true)
  apply({ categories: ['Saved'] })
  pending[2]({ categories: ['Renamed'] }); await third
  assert.deepEqual(settings.value.categories, ['Saved'])
})

test('only filters behind the Filters button count as active chips', async () => {
  const { activeTicketFilters, emptyTicketFilters } = await import('../src/services/ticketSettings.js')
  assert.deepEqual(activeTicketFilters(emptyTicketFilters()), [])
  assert.deepEqual(activeTicketFilters({ ...emptyTicketFilters(), query: 'parcel', ticket_status: 'Open', mine: 'assigned', category: 'Support', assigned_to: 'a@x.invalid' }), ['category', 'assigned_to'])
})
