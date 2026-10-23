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
