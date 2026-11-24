import { objectValue } from '../components/messageContent.js'
import { phoneCaption } from './phoneNumber.js'

// A thread is one contact endpoint on one of our channels, such as a customer's number on our Sales number.
// Replies stay on the thread; only a new conversation picks a channel.

const PROVIDER_ICONS = { WhatsApp: 'message-circle', Telegram: 'send', Email: 'mail' }

export function providerIcon(provider) {
  return PROVIDER_ICONS[provider] || 'message-square'
}

// A WhatsApp number reads as a phone number; a Telegram chat id or an email address stays as it is.
export function endpointLabel(endpoint, provider = 'WhatsApp') {
  // A Telegram chat id means nothing to people; the server's endpoint_label names the linked mobile instead.
  if (provider === 'Telegram') return /^-?\d+$/.test(String(endpoint || '').trim()) ? '' : endpoint || ''
  return (provider === 'WhatsApp' && phoneCaption(endpoint)) || endpoint || ''
}

// What a person sees for a thread or channel mark: a Telegram chat's linked mobile, username or name, else the address.
export function addressLabel(item) {
  if (item?.provider === 'Telegram') return phoneCaption(item.endpoint_label) || item.endpoint_label || item.handle || endpointLabel(item.endpoint, 'Telegram')
  return endpointLabel(item?.endpoint, item?.provider)
}

export function threadMatches(thread, channel, endpoint) {
  return !!thread && thread.channel === channel && (thread.endpoint || '') === (endpoint || '')
}

export function newestThread(threads) {
  if (!threads?.length) return null
  return threads.reduce((best, thread) => (thread.last_message || '') > (best.last_message || '') ? thread : best)
}

// The thread a record opens on: the routed one, else the one with the newest unread message, else the newest.
export function openingThread(threads, routedKey = '') {
  if (!threads?.length) return null
  const routed = routedKey && threads.find(thread => thread.key === routedKey)
  if (routed) return routed
  const unread = threads.filter(thread => thread.unread > 0)
  return newestThread(unread.length ? unread : threads)
}

// A thread read from its newest message, for the moment before the thread list has the thread.
export function sourceThread(message) {
  if (!message) return null
  const provider = objectValue(message.provider_context).provider || ''
  return { key: [message.relay_contact, message.channel, message.sender_endpoint || ''].join('|'), relay_contact: message.relay_contact,
    contact_label: message.contact_label || '', frappe_contact: message.frappe_contact || '', channel: message.channel, provider,
    channel_label: message.channel_title || message.channel, channel_address: '', endpoint: message.sender_endpoint || '', unread: 0 }
}

// The thread a contact link names: its newest thread with unread messages, else its newest one.
export function contactThread(threads, frappeContact) {
  return openingThread((threads || []).filter(thread => thread.frappe_contact === frappeContact))
}

// Tab text: the endpoint, with the person's name when the record has several people, and our channel when the
// record talks on more than one of our channels of that kind, such as two WhatsApp numbers.
export function threadTabs(threads) {
  const list = threads || [], manyPeople = hasManyPeople(list)
  const ours = provider => new Set(list.filter(thread => thread.provider === provider).map(thread => thread.channel)).size
  return list.map(thread => ({ thread, icon: providerIcon(thread.provider), provider: thread.provider || 'Chat',
    endpoint: threadAddress(thread), person: manyPeople ? thread.contact_label || '' : '',
    via: ours(thread.provider) > 1 ? thread.channel_label || thread.channel : '', from: ourChannel(thread),
    title: [thread.provider || 'Chat', threadAddress(thread), manyPeople && thread.contact_label, ourChannel(thread) && 'to our ' + ourChannel(thread)]
      .filter(Boolean).join(' · ') }))
}

// The person's side of a thread: a Telegram handle when Telegram sent one, else the endpoint.
export function threadAddress(thread) {
  return addressLabel(thread)
}

export function hasManyPeople(threads) {
  return new Set((threads || []).map(thread => thread.relay_contact)).size > 1
}

// Our side of the thread: "Sales · +91 70000 00001", or the mailbox for email.
export function ourChannel(thread) {
  const label = thread?.channel_label || thread?.channel || ''
  const address = endpointLabel(thread?.channel_address || '', thread?.provider)
  return [label, address].filter((value, index, list) => value && list.indexOf(value) === index).join(' · ')
}

// The composer's lock line: the reply goes on this thread's channel, to its endpoint, from our channel.
export function replyLock(thread) {
  if (!thread) return null
  const email = thread.provider === 'Email'
  return { icon: providerIcon(thread.provider), verb: email ? 'Replying by' : 'Replying on', provider: thread.provider || 'Chat',
    to: threadAddress(thread) || thread.contact_label || 'Contact', from: ourChannel(thread), note: email ? 'subject kept' : '' }
}

export function replyLockText(thread) {
  const lock = replyLock(thread)
  return lock ? `${lock.verb} ${lock.provider} to ${lock.to}${lock.from ? ' from ' + lock.from : ''}` : ''
}

// The list row's channel marks: one per endpoint, the ones holding unread messages marked.
export function rowChannels(row, limit = 5) {
  const marks = Array.isArray(row?.threads) ? row.threads : []
  return marks.slice(0, limit).map(mark => ({ ...mark, icon: providerIcon(mark.provider),
    label: `${mark.provider || 'Chat'} ${addressLabel(mark)}`.trim() + (mark.unread ? ', unread' : '') }))
}

// "Waiting 2d": the customer wrote last, everyone has read it and no one has replied for an hour or more.
export function waitingLabel(row, now = Date.now()) {
  if (row?.last_direction !== 'Incoming' || row.unread) return ''
  const at = Date.parse(String(row.latest_at || row.last_message_at || '').replace(' ', 'T'))
  if (Number.isNaN(at)) return ''
  const hours = Math.floor((now - at) / 3600000)
  if (hours < 1) return ''
  return hours < 24 ? `Waiting ${hours}h` : `Waiting ${Math.floor(hours / 24)}d`
}
