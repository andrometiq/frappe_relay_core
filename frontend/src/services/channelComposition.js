import { objectValue } from '../components/messageContent.js'

export function compositionScope(message, user = '') {
  if (!message) return ''
  const context = objectValue(message.provider_context)
  return JSON.stringify([user, message.business_doctype, message.business_name, message.relay_contact,
    message.channel, message.sender_endpoint, context.message_thread_id, context.email_thread_id, message.name])
}
export function channelStatus(message) {
  const provider = objectValue(message.provider_context).provider
  if (provider === 'WhatsApp') return message.status
  if (provider === 'Email' && message.status === 'Failed' && !message._pending) return 'Bounced'
  const status = { Sending: 'Queued', Dispatching: 'Queued', Pending: 'Queued', Unconfirmed: 'Uncertain', Failed: 'Rejected' }[message.status] || message.status
  if (['Sent', 'Submitted'].includes(status)) return provider === 'Telegram' ? 'Bot accepted' : 'SMTP accepted'
  if (status === 'Read') return 'Read by agent'
  return status
}
export function telegramLimit(kind) { return kind === 'text' ? 4096 : 1024 }
export function addressList(text) {
  const addresses = [...new Set(String(text || '').split(/[,;\n]/).map(value => value.trim().toLowerCase()).filter(Boolean))]
  if (addresses.some(value => !/^[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+$/.test(value))) throw Error('Use plain email addresses separated by commas.')
  return addresses
}
export function emailComposition(message, mode = 'reply') {
  const context = objectValue(message.provider_context), data = objectValue(message.message_data)
  const email = data.email || data
  const subject = email.subject || context.subject || ''
  const to = mode === 'forward' ? [] : [message.sender_endpoint]
  const cc = mode === 'reply-all' ? [...(context.to || email.to || []), ...(context.cc || email.cc || [])]
    .filter(value => typeof value === 'string' && !to.includes(value)) : []
  return { mode, to: to.join(', '), cc: [...new Set(cc)].join(', '), bcc: '',
    subject: (mode === 'forward' ? /^fwd?:/i : /^re:/i).test(subject) ? subject : (mode === 'forward' ? 'Fwd: ' : 'Re: ') + subject,
    body: mode === 'forward' ? 'Forwarded message:\n' + (message.content || '') : '', attachments: [], signature: '', request: null }
}
