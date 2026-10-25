// The backend owns the switch through api.capabilities enabled_channels.
export function channelEnabled(capabilities, provider) {
  return !provider || (capabilities?.enabled_channels || []).includes(provider)
}

// Inbox filters offer "All channels" only when no supported provider is switched off.
export function mediumOptions(capabilities) {
  const enabled = capabilities?.enabled_channels || []
  const all = ['WhatsApp', 'Telegram', 'Email'].every(provider => enabled.includes(provider))
  return all ? [{ label: 'All channels', value: 'all' }, ...enabled] : enabled
}

// Message bubbles name their channel only when more than one channel is switched on.
export function multipleChannels(capabilities) {
  return (capabilities?.enabled_channels || []).length > 1
}
