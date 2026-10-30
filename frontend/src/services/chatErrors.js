// Plain sentences for chat problems that staff cannot fix themselves.
export function channelOffText(provider) {
  return !provider || provider === 'WhatsApp'
    ? 'This WhatsApp number is switched off. Ask your manager.'
    : `This ${provider} channel is switched off. Ask your manager.`
}

export function plainChatError(message) {
  return /channel is disabled or belongs to another account/i.test(message || '') ? channelOffText('WhatsApp') : message || ''
}

// A chat shows a reply box only after a WhatsApp message; until then this says what staff can do instead.
export function noReplyText({ contact = null, choosing = false } = {}) {
  if (choosing) return 'Choose a contact above to reply on WhatsApp.'
  if (!contact) return 'No WhatsApp chat yet. Start one with a template.'
  if (!contact.phone) return `${contact.label} has no mobile number for WhatsApp. Add one to the contact first.`
  if (contact.number_elsewhere) return `${contact.label}'s mobile number is saved on another contact too, so WhatsApp cannot start here. Ask a manager to keep it on one contact only.`
  return `No WhatsApp chat with ${contact.label} yet. Start one with a template.`
}

// Starting a chat needs a number this contact owns; an unpicked contact is chosen in the start dialog.
export function canStartChat(contact) {
  return !contact || (!!contact.phone && !contact.number_elsewhere)
}
