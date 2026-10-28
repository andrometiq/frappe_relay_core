import { phoneCaption } from './phoneNumber.js'

// Keep identifiers for navigation and writes; never use generated keys as captions.
export function readableName(value, fallback = 'Record') {
  let text = typeof value === 'string' ? value.trim() : ''
  // Local acceptance fixtures append a nanosecond run key; retain it in the
  // stored value/details, not the human caption. Never alter business numbers.
  if (/^(?:Local\s|Notification\s)/i.test(text)) text = text.replace(/\s+\d{16,20}$/, '')
  if (/^\d{10,15}$/.test(text)) return phoneCaption(text) || `+${text}`
  return !text || /^(?:RELAY-[A-Z]+|TKT)-\d+$/i.test(text) || /^\d{16,}$/.test(text) || /^(?:[a-f0-9]{32}|[a-f0-9]{40}|[a-f0-9]{64})$/i.test(text) ? fallback : text
}

export function recordTitle(record, fallback = 'Record') {
  if (!record || typeof record !== 'object') return readableName(record, fallback)
  return readableName(record.title || record.subject || record.full_name || record.display_name || record.label || record.template_name || record.name, fallback)
}
