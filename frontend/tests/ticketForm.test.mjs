import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { TICKET_PRIORITIES, ticketNotice, ticketPayload, ticketRoute, ticketSubject, withMention } from '../src/services/ticketForm.js'

test('ticket subject uses the message text on one line within the subject limit', () => {
  assert.equal(ticketSubject({ content: '  Parcel\n arrived   damaged ' }), 'Parcel arrived damaged')
  assert.equal(ticketSubject({ content: 'x'.repeat(200) }).length, 140)
  assert.equal(ticketSubject({ content: '' }, 'Follow up with Ravi'), 'Follow up with Ravi')
  assert.equal(ticketSubject(null, 'Follow up'), 'Follow up')
})

test('ticket payload trims text and sends assignee, tags and quoted message', () => {
  const form = { subject: ' Damaged ', brief: ' Call back ', priority: 'High', assignedTo: 'a@example.invalid', tagged: ['b@example.invalid'] }
  assert.deepEqual(ticketPayload(form, ['RELAY-MSG-0000000001']), { subject: 'Damaged', brief: 'Call back', priority: 'High',
    assigned_to: 'a@example.invalid', tagged: ['b@example.invalid'], messages: ['RELAY-MSG-0000000001'] })
  assert.equal(ticketPayload({ ...form, assignedTo: '' }, []).assigned_to, '')
  assert.deepEqual(TICKET_PRIORITIES, ['Low', 'Medium', 'High', 'Urgent'])
})

test('mentions add one @name to the comment text', () => {
  assert.equal(withMention('', 'Ravi Kumar'), '@Ravi Kumar ')
  assert.equal(withMention('Please check', 'Ravi'), 'Please check @Ravi ')
  assert.equal(withMention('@Ravi please check', 'Ravi'), '@Ravi please check')
})

test('live ticket notices link to the ticket and ignore other events', () => {
  assert.equal(ticketRoute('RELAY-TKT-0000000001'), '#/tickets?ticket=RELAY-TKT-0000000001')
  assert.deepEqual(ticketNotice({ ticket: 'RELAY-TKT-0000000001', subject: 'Damaged parcel', action: 'Asha assigned you a ticket' }),
    { id: 'RELAY-TKT-0000000001:Asha assigned you a ticket', title: 'Asha assigned you a ticket', text: 'Damaged parcel', href: '#/tickets?ticket=RELAY-TKT-0000000001' })
  assert.equal(ticketNotice({ kind: 'tickets' }), null)
})

test('chat header and message menu open the create ticket dialog', async () => {
  const inbox = await readFile(new URL('../src/components/ConnectedMessages.vue', import.meta.url), 'utf8')
  const thread = await readFile(new URL('../src/components/messages/MessageThread.vue', import.meta.url), 'utf8')
  assert.match(inbox, /title="Create ticket"[^>]*@click="openTicket\(\)"/)
  assert.match(inbox, /@ticket="openTicket"/)
  assert.match(thread, /label: "Create ticket",\s*icon: "bookmark",\s*onClick: \(\) => emit\("ticket", message\)/)
  const tickets = await readFile(new URL('../src/components/TicketsWorkspace.vue', import.meta.url), 'utf8')
  assert.match(tickets, /value: 'assigned', label: 'Assigned to me'/)
  assert.match(tickets, /value: 'tagged', label: 'Tagged me'/)
})
