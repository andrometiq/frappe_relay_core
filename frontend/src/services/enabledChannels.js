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

// One feature of an enabled channel from api.capabilities channels, such as 'templates' or 'media.voice'.
export function channelFeature(capabilities, provider, feature) {
  return feature.split('.').reduce((value, key) => value?.[key], capabilities?.channels?.[provider])
}

export function channelCan(capabilities, provider, feature) {
  return Boolean(channelFeature(capabilities, provider, feature))
}

// Message types the composer offers for the source channel. Groups take media only.
export function composerKinds(capabilities, context) {
  const can = feature => channelCan(capabilities, context.provider, feature)
  const media = ['sticker', 'photo', 'video', 'audio', 'voice', 'document'].filter(kind => can('media.' + kind))
  const cards = context.group_id ? [] : [['location', 'location'], ['contacts', 'contact']].filter(([feature]) => can(feature))
  return ['text', ...media, ...cards.map(([, kind]) => kind)]
}
