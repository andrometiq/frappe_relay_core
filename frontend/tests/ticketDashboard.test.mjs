import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = file => readFileSync(new URL('../src/components/' + file, import.meta.url), 'utf8')

test('the owner KPI is named Assigned, so it cannot be read as the In progress status row', () => {
  const dashboard = read('tickets/TicketDashboard.vue')
  assert.match(dashboard, /label: 'Assigned', [^}]*value: totals\.assigned,/)
  assert.doesNotMatch(dashboard, /totals\.in_progress|label: 'In progress'/)
})

test('Others gets a group icon, not the Unassigned person avatar', () => {
  const dashboard = read('tickets/TicketDashboard.vue')
  assert.match(dashboard, /row\.key === 'others'" class="ticket-bar__group"[^>]*><Users /)
})

test('bars show a visible track and give phone names the full row width', () => {
  const dashboard = read('tickets/TicketDashboard.vue')
  assert.match(dashboard, /\.ticket-bar__track \{[^}]*background: var\(--surface-gray-4\)/)
  assert.match(dashboard, /@media \(max-width: 900px\)[\s\S]*grid-template-areas: 'label value' 'track track'/)
})

test('the second press of a double-click on the mask does not close the ticket', () => {
  const dialog = read('tickets/TicketDialog.vue')
  const handler = new Function('event', dialog.match(/const keepOpenOnDoubleClick = event => \{ (.*) \}\n/)[1])
  const press = (detail, mask) => {
    let stopped = false
    handler({ detail, target: { classList: { contains: name => mask && name === 'relay-dialog-mask' } }, stopPropagation: () => { stopped = true } })
    return stopped
  }
  assert.equal(press(2, true), true)
  assert.equal(press(1, true), false)
  assert.equal(press(2, false), false)
  assert.match(dialog, /addEventListener\('mousedown', keepOpenOnDoubleClick, true\)/)
  assert.match(dialog, /removeEventListener\('mousedown', keepOpenOnDoubleClick, true\)/)
})
