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
  if (hasMention(body, label)) return body
  return (body && !/\s$/.test(body) ? body + ' ' : body) + '@' + label + ' '
}

// "@Label" stands in the text as a whole word: "@Sam" is not inside "@Samantha".
export function hasMention(text, label) {
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp('(^|\\s)@' + escaped + '(?![\\p{L}\\p{N}_])', 'u').test(text)
}

// The enabled business types of business_types.list_types as picker options.
export function businessTypeOptions(rows) {
  return (rows || []).filter(row => row.enabled).map(row => ({ value: row.business_doctype, label: row.label || row.business_doctype }))
}

// Where the mention list opens: below the text area, or above it when the space below is too small.
export function mentionListPlacement(rect, viewportHeight, listHeight = 220) {
  const below = viewportHeight - rect.bottom - 12, above = rect.top - 12
  const up = below < Math.min(listHeight, 160) && above > below
  const space = Math.max(up ? above : below, 120)
  return { left: rect.left + 'px', width: rect.width + 'px', maxHeight: Math.min(listHeight, space) + 'px',
    ...(up ? { bottom: viewportHeight - rect.top + 4 + 'px' } : { top: rect.bottom + 4 + 'px' }) }
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
  return [...picked].filter(([, label]) => hasMention(text, label)).map(([user]) => user)
}

// Colleagues of a chat ticket are those who read its contact; a ticket without a chat offers every Relay user.
export function colleagueRequest(contact, query) {
  return contact ? ['collaboration.colleagues', { contact, query }] : ['tickets.colleagues', { query }]
}
