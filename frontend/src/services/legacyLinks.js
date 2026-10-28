// A WhatsApp Core chat link (#/inbox/<conversation>) opens the Relay chat its import became, when the user may read it.
export function legacyConversation(hash) {
  const [path, query] = hash.slice(1).split('?')
  return path === '/messages' ? new URLSearchParams(query || '').get('legacy_conversation') : null
}

export async function openLegacyConversation(location, api) {
  const conversation = legacyConversation(location.hash)
  if (!conversation) return
  let contact = null
  try { contact = (await api('whatsapp_redirects.conversation_contact', { conversation })).contact } catch { contact = null }
  location.replace(contact ? '#/messages?contact=' + encodeURIComponent(contact) : '#/messages')
}
