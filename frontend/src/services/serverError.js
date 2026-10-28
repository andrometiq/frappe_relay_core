// Render validation messages as text; never expose traceback/exception payloads.
export function serverError(body, fallback) {
  let messages = body?._server_messages
  try { if (typeof messages === 'string') messages = JSON.parse(messages) } catch { messages = [] }
  if (Array.isArray(messages)) {
    const text = messages.map(item => {
      try { if (typeof item === 'string') item = JSON.parse(item) } catch { return '' }
      return typeof item?.message === 'string' ? item.message.replace(/<[^>]*>/g, '') : ''
    }).filter(Boolean).join('\n')
    if (text) return text
  }
  return typeof body?.message === 'string' ? body.message.replace(/<[^>]*>/g, '') : fallback
}

// A provider that answered with a web page (for example a 404) stored the whole page as the error; show a short reason.
export function deliveryError(text) {
  if (!/<!doctype html|<html[\s>]/i.test(text || '')) return text
  const title = text.match(/<title[^>]*>([^<]*)<\/title>|<meta name="title" content="([^"]*)"/i)
  const reason = (title?.[1] || title?.[2] || '').trim()
  return 'Send failed: the server returned a web page' + (reason ? ` (${reason})` : '') + ' instead of a WhatsApp reply.'
}
