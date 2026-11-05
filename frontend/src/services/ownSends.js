import { ref } from 'vue'

// Sends made in this browser. A chat list moves the sent conversation's row itself, and the live events of these
// messages then read nothing. Names are kept for a minute, longer than their status updates take to arrive.
const KEEP_MS = 60000
const sent = new Map()
export const lastOwnSend = ref(null)

// The composer calls this when it shows the pending bubble: conversation is { contact, business_doctype, business_name, preview }.
export function announceOwnSend(conversation, now = Date.now()) {
  lastOwnSend.value = { ...conversation, at: now }
}

export function recordOwnMessages(conversation, names, now = Date.now()) {
  for (const [name, entry] of sent) if (now - entry.at > KEEP_MS) sent.delete(name)
  for (const name of names) if (name) sent.set(name, { ...conversation, at: now })
}

export const ownSendOf = name => sent.get(name)
