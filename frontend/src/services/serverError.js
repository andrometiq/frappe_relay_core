const ENTITIES = { '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'", '&amp;': '&' }
const plain = text => text.replace(/<[^>]*>/g, '').replace(/&(?:lt|gt|quot|#39|amp);/g, entity => ENTITIES[entity])

// Render validation messages as text; never expose traceback/exception payloads.
export function serverError(body, fallback) {
  let messages = body?._server_messages
  try { if (typeof messages === 'string') messages = JSON.parse(messages) } catch { messages = [] }
  if (Array.isArray(messages)) {
    const text = messages.map(item => {
      try { if (typeof item === 'string') item = JSON.parse(item) } catch { return '' }
      return typeof item?.message === 'string' ? plain(item.message) : ''
    }).filter(Boolean).join('\n')
    if (text) return text
  }
  return typeof body?.message === 'string' ? plain(body.message) : fallback
}

// Plain reason for a failed request whose response carries no readable message.
export function requestFailure(status, write) {
  if (status === 401) return 'Your session has expired. Sign in again to continue.'
  if (status === 403) return 'You do not have permission for this action.'
  if (status === 404) return 'This action is not available. Reload the page and try again.'
  if (status === 413) return 'The file is too large for the server. Choose a smaller file.'
  if (status === 429) return 'Too many requests. Wait a moment and try again.'
  if ([502, 503, 504].includes(status)) {
    return write ? 'The server is busy and did not confirm this action. Check whether it was done before you try again.'
      : 'The server is busy. Try again in a moment.'
  }
  return write ? 'The server could not finish this action. Try again. If it happens again, tell your administrator.'
    : 'The server could not load this. Try again. If it happens again, tell your administrator.'
}

// A provider that answered with a web page (for example a 404) stored the whole page as the error; show a short reason.
export function deliveryError(text) {
  if (!/<!doctype html|<html[\s>]/i.test(text || '')) return text
  const title = text.match(/<title[^>]*>([^<]*)<\/title>|<meta name="title" content="([^"]*)"/i)
  const reason = (title?.[1] || title?.[2] || '').trim()
  return 'Send failed: the server returned a web page' + (reason ? ` (${reason})` : '') + ' instead of a WhatsApp reply.'
}
