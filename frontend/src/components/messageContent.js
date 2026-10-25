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

export function transcriptState(message) {
  if (message.transcript) return { state: 'available', text: message.transcript }
  const labels = { Pending: 'Transcript pending…', Failed: 'Transcript unavailable: transcription failed',
    Unavailable: 'Transcript unavailable: no transcription provider is set up' }
  return labels[message.transcript_status]
    ? { state: message.transcript_status.toLowerCase(), text: labels[message.transcript_status] }
    : { state: 'legacy', text: '' }
}

export function unsupportedNotice(data) {
  const value = data.unsupported || {}
  const meta = [value.details || value.title, value.code ? 'code ' + value.code : ''].filter(Boolean).join(' · ')
  return { reason: value.reason || 'This message type is not supported', meta }
}

export function orderLines(data) {
  return (data.order?.items || []).slice(0, 100).map(item => {
    const price = typeof item.item_price === 'number' ? ` · ${item.currency || ''} ${item.item_price}`.replace('  ', ' ') : ''
    return `${item.quantity ?? 1} × ${item.product_retailer_id || 'Product'}${price}`
  })
}

// Sent templates keep their rendered parts beside the template name.
export function templateParts(data) {
  const template = data?.template
  if (!template?.name) return null
  return {
    header: template.header || '',
    footer: template.footer || '',
    buttons: Array.isArray(template.buttons) ? template.buttons : [],
    caption: typeof data.campaign === 'string' && data.campaign ? `Campaign: ${data.campaign}` : `Template · ${template.name}`,
  }
}
