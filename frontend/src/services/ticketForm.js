// A ticket subject is the message text on one line, cut to the 140-character limit.
export function ticketSubject(message, fallback = '') {
  const text = String(message?.content || '').replace(/\s+/g, ' ').trim()
  return (text || fallback).slice(0, 140)
}

export function ticketPayload(form, messages) {
  return {
    subject: form.subject.trim(), brief: form.brief.trim(), ...(form.ticketType ? { ticket_type: form.ticketType } : {}),
    assigned_to: form.assignedTo || '', messages,
  }
}

// Picking a colleague in the mention field also writes "@Name" into the text.
export function withMention(body, label) {
  const mention = '@' + label
  if (body.includes(mention)) return body
  return (body && !/\s$/.test(body) ? body + ' ' : body) + mention + ' '
}

export function ticketRoute(ticket) {
  return '#/tickets?ticket=' + encodeURIComponent(ticket)
}

export function ticketNotice(event) {
  if (!event?.ticket) return null
  return { id: event.ticket + ':' + (event.action || ''), title: event.action || 'Ticket update', text: event.subject || event.ticket, href: ticketRoute(event.ticket) }
}

// Two people with the same name show their login under the name, so a picker never lists one name twice.
export function distinctPeople(rows) {
  const seen = new Map()
  for (const row of rows) seen.set(row.label, (seen.get(row.label) || 0) + 1)
  return rows.map(row => seen.get(row.label) > 1 ? { ...row, description: row.value } : row)
}

// The "@name" being typed just before the caret, or null.
export function mentionQuery(text, caret) {
  const match = /(^|\s)@([^\s@]{0,40})$/.exec(text.slice(0, caret))
  return match ? { start: caret - match[2].length - 1, query: match[2] } : null
}

// Replace the typed "@name" with the picked colleague's "@Label ".
export function insertMention(text, start, caret, label) {
  return text.slice(0, start) + '@' + label + ' ' + text.slice(caret)
}

// The picked colleagues whose "@Label" is still in the text.
export function mentionedUsers(text, picked) {
  return [...picked].filter(([, label]) => text.includes('@' + label)).map(([user]) => user)
}

// Colleagues of a chat ticket are those who read its contact; a ticket without a chat offers every Relay user.
export function colleagueRequest(contact, query) {
  return contact ? ['collaboration.colleagues', { contact, query }] : ['tickets.colleagues', { query }]
}
