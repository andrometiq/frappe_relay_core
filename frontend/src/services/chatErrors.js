// Plain sentences for chat problems that staff cannot fix themselves.
export function channelOffText(provider) {
  return !provider || provider === 'WhatsApp'
    ? 'This WhatsApp number is switched off. Ask your manager.'
    : `This ${provider} channel is switched off. Ask your manager.`
}

export function plainChatError(message) {
  return /channel is disabled or belongs to another account/i.test(message || '') ? channelOffText('WhatsApp') : message || ''
}
