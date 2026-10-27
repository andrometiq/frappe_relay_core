export const TICKET_PRIORITIES = ['Low', 'Medium', 'High', 'Urgent']

// A ticket subject is the message text on one line, cut to the 140-character limit.
export function ticketSubject(message, fallback = '') {
  const text = String(message?.content || '').replace(/\s+/g, ' ').trim()
  return (text || fallback).slice(0, 140)
}

export function ticketPayload(form, messages) {
  return {
    subject: form.subject.trim(), brief: form.brief.trim(), priority: form.priority,
    assigned_to: form.assignedTo || '', tagged: [...form.tagged], messages,
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
