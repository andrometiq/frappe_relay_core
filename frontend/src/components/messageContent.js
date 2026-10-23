export function objectValue(value) {
  if (typeof value === 'string') {
    try { value = JSON.parse(value) } catch { return {} }
  }
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

export function messageData(message) {
  const value = objectValue(message.message_data)
  return value.kind ? value : { kind: message.message_type || 'text', text: message.content || '' }
}

export function stickerURL(name) {
  return /^RELAY-MSG-\d{10}$/.test(name || '')
    ? '/api/method/relay_core.messaging.sticker?message=' + encodeURIComponent(name) : ''
}

export function mapURL(location) {
  const latitude = location?.latitude, longitude = location?.longitude
  if (typeof latitude !== 'number' || typeof longitude !== 'number'
      || !Number.isFinite(latitude) || !Number.isFinite(longitude)
      || Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return ''
  return `https://www.openstreetmap.org/?mlat=${latitude}&mlon=${longitude}#map=16/${latitude}/${longitude}`
}

export function reactionLabels(value) {
  const state = objectValue(value), labels = []
  if (Array.isArray(state._counts)) {
    return state._counts.slice(0, 20).map(entry => `${entry.type?.emoji || 'Reaction'} ${Number(entry.count) || 0}`)
  }
  for (const [actor, entries] of Object.entries(state).slice(0, 201)) {
    if (!Array.isArray(entries)) continue
    for (const entry of entries.slice(0, 20)) {
      if (actor === '_counts') labels.push(`${entry.type?.emoji || 'Reaction'} ${Number(entry.count) || 0}`)
      else labels.push(entry.emoji || (entry.type === 'custom_emoji' ? 'Custom reaction' : 'Reaction'))
    }
  }
  return [...new Set(labels)]
}

export function attachmentDownloadURL(message) {
  if (message._pending || !message.name || !['photo','image','video','audio','voice','document','animation'].includes(messageData(message).kind)) return null;
  return '/api/method/relay_core.attachments.read?message=' + encodeURIComponent(message.name) + '&download=1';
}
