import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { colleagueRequest, distinctPeople, insertMention, mentionQuery, mentionedUsers, ticketNotice, ticketPayload, ticketRoute, ticketSubject, withMention } from '../src/services/ticketForm.js'

test('ticket subject uses the message text on one line within the subject limit', () => {
  assert.equal(ticketSubject({ content: '  Parcel\n arrived   damaged ' }), 'Parcel arrived damaged')
  assert.equal(ticketSubject({ content: 'x'.repeat(200) }).length, 140)
  assert.equal(ticketSubject({ content: '' }, 'Follow up with Ravi'), 'Follow up with Ravi')
  assert.equal(ticketSubject(null, 'Follow up'), 'Follow up')
})

test('ticket payload trims text and sends assignee, type and quoted message', () => {
  const form = { subject: ' Damaged ', brief: ' Call back ', ticketType: '', assignedTo: 'a@example.invalid' }
  assert.deepEqual(ticketPayload(form, ['RELAY-MSG-0000000001']), { subject: 'Damaged', brief: 'Call back',
    assigned_to: 'a@example.invalid', messages: ['RELAY-MSG-0000000001'] })
  assert.equal(ticketPayload({ ...form, assignedTo: '' }, []).assigned_to, '')
  assert.equal(ticketPayload({ ...form, ticketType: 'Payment' }, []).ticket_type, 'Payment')
})

test('mentions add one @name to the comment text', () => {
  assert.equal(withMention('', 'Ravi Kumar'), '@Ravi Kumar ')
  assert.equal(withMention('Please check', 'Ravi'), 'Please check @Ravi ')
  assert.equal(withMention('@Ravi please check', 'Ravi'), '@Ravi please check')
})

test('live ticket notices link to the ticket and ignore other events', () => {
  assert.equal(ticketRoute('TKT-00001'), '#/tickets?ticket=TKT-00001')
  assert.deepEqual(ticketNotice({ ticket: 'TKT-00001', subject: 'Damaged parcel', action: 'Asha assigned you a ticket' }),
    { id: 'TKT-00001:Asha assigned you a ticket', title: 'Asha assigned you a ticket', text: 'Damaged parcel', href: '#/tickets?ticket=TKT-00001' })
  assert.equal(ticketNotice({ kind: 'tickets' }), null)
})

test('message selection and the message menu open the create ticket dialog', async () => {
  const inbox = await readFile(new URL('../src/components/ConnectedMessages.vue', import.meta.url), 'utf8')
  const thread = await readFile(new URL('../src/components/messages/MessageThread.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(inbox, /Create ticket from this chat|openTicket\(\)/)
  assert.match(inbox, /@ticket="openTicket"/)
  assert.match(thread, /label: "Create ticket",\s*icon: "bookmark",\s*onClick: \(\) => emit\("ticket", message\)/)
  assert.match(thread, /emit\('ticket', selectedMessages\.value\)/)
})

test('people with the same name show their login so a picker never lists one name twice', () => {
  const rows = distinctPeople([{ value: 'a@x.invalid', label: 'MRP' }, { value: 'b@x.invalid', label: 'MRP' }, { value: 'c@x.invalid', label: 'Asha' }])
  assert.deepEqual(rows.map(row => row.description), ['a@x.invalid', 'b@x.invalid', undefined])
})

test('typing @ before the caret starts a mention; an e-mail address does not', () => {
  assert.deepEqual(mentionQuery('Please ask @Pra', 15), { start: 11, query: 'Pra' })
  assert.deepEqual(mentionQuery('@', 1), { start: 0, query: '' })
  assert.equal(mentionQuery('mail ops@example.invalid', 24), null)
  assert.equal(mentionQuery('@Prakash done', 13), null, 'Text after a space ends the mention')
})

test('a picked colleague replaces the typed name and stays mentioned while its label is in the text', () => {
  const text = insertMention('Please ask @Pra today', 11, 15, 'Prakash S')
  assert.equal(text, 'Please ask @Prakash S  today')
  const picked = new Map([['p@example.invalid', 'Prakash S'], ['r@example.invalid', 'Ravi']])
  assert.deepEqual(mentionedUsers(text, picked), ['p@example.invalid'])
  assert.deepEqual(mentionedUsers('No mentions left', picked), [])
})

test('a ticket without a chat searches every Relay colleague', () => {
  assert.deepEqual(colleagueRequest('RELAY-CON-1', 'ra'), ['collaboration.colleagues', { contact: 'RELAY-CON-1', query: 'ra' }])
  assert.deepEqual(colleagueRequest('', 'ra'), ['tickets.colleagues', { query: 'ra' }])
})
