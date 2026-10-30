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

// The emoji this site reacted with; the server stores it under "bot".
export function ownReaction(value) {
  const own = objectValue(value).bot
  return Array.isArray(own) ? own[0]?.emoji || '' : ''
}

// The image, video or document parameter a template header sent.
function templateHeaderParameter(data) {
  for (const component of data?.template?.components || []) {
    if (String(component?.type).toLowerCase() !== 'header') continue
    for (const parameter of component.parameters || []) {
      const media = parameter?.[parameter?.type]
      if (['image', 'video', 'document'].includes(parameter?.type) && media && typeof media === 'object') return parameter
    }
  }
  return null
}

// The image, video or document a template header sent, as its send parameter.
export function templateHeaderMedia(data) {
  const parameter = templateHeaderParameter(data)
  return parameter ? parameter[parameter.type] : null
}

const httpsLink = value => typeof value === 'string' && /^https:\/\//i.test(value) ? value : ''

// The header media a sent template shows: Core serves a kept copy or a media ID, else its https link loads.
export function templateHeaderView(message) {
  const data = messageData(message), parameter = templateHeaderParameter(data)
  const fileName = typeof data.template?.document?.file_name === 'string' ? data.template.document.file_name : ''
  const type = parameter?.type || (fileName ? 'document' : '')
  if (!type) return null
  const media = parameter?.[type] || {}
  return {
    type, fileName: media.filename || fileName,
    kept: Boolean(!message._pending && message.name && (data.attachment || media.id)),
    link: httpsLink(media.link),
  }
}

// Core serves received media, kept copies and template headers sent by media ID; a header sent by link downloads from it.
export function attachmentDownloadURL(message) {
  if (message._pending || !message.name) return null;
  const data = messageData(message), header = templateHeaderMedia(data);
  if (['photo','image','video','audio','voice','document','animation'].includes(data.kind) || data.attachment || header?.id)
    return '/api/method/relay_core.attachments.read?message=' + encodeURIComponent(message.name) + '&download=1';
  return httpsLink(header?.link) || null;
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

export function attachmentKind(kind) {
  if (['photo', 'image'].includes(kind)) return 'image'
  if (['video', 'animation'].includes(kind)) return 'video'
  return ['audio', 'voice'].includes(kind) ? 'audio' : 'document'
}

// Short file type for a document card, from the file name or else the MIME type.
export function documentType(media) {
  const extension = /\.([A-Za-z0-9]{1,8})$/.exec(media?.file_name || media?.filename || '')?.[1]
  const subtype = String(media?.mime_type || '').split(';')[0].split('/')[1] || ''
  return extension ? extension.toUpperCase() : subtype && subtype.length <= 8 ? subtype.toUpperCase() : 'Document'
}
