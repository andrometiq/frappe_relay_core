import { channelEnabled } from './enabledChannels.js'

// Settings sidebar. Access lives on its own page (#/teams) so every Relay user can read their own access.
const SECTIONS = [
  { key: 'start', items: [{ key: 'overview', label: 'Setup checklist', icon: 'clipboard-list' }] },
  { key: 'channels', title: 'Channels', items: [
    { key: 'whatsapp', label: 'WhatsApp numbers', icon: 'phone', channel: 'WhatsApp' },
    { key: 'telegram', label: 'Telegram', icon: 'send', channel: 'Telegram' },
    { key: 'email', label: 'Email', icon: 'mail', channel: 'Email' },
  ] },
  { key: 'people', title: 'People', items: [
    { key: 'access', label: 'Access', icon: 'user-check', open: true },
    { key: 'business-types', label: 'Business types', icon: 'users' },
  ] },
  { key: 'messages', title: 'Messages', items: [
    { key: 'replies', label: 'Quick replies', icon: 'zap' },
    { key: 'tickets', label: 'Ticket statuses and types', icon: 'ticket' },
    { key: 'features', label: 'Features', icon: 'sparkles' },
  ] },
  { key: 'account', title: 'Account', items: [
    { key: 'billing', label: 'Billing', icon: 'credit-card', configure: true, channel: 'WhatsApp' },
    { key: 'hub', label: 'Hub connection', icon: 'link' },
  ] },
]

// Items this person may open: managers see Settings; everyone sees Access.
export function settingsSections(capabilities) {
  const manage = Boolean(capabilities?.manage)
  return SECTIONS.map(section => ({ ...section, items: section.items.filter(item => (manage || item.open)
    && (!item.configure || capabilities?.configure) && channelEnabled(capabilities, item.channel)) }))
    .filter(section => section.items.length)
}

export function settingsRoute(key) {
  return key === 'access' ? '#/teams' : key === 'overview' ? '#/settings' : '#/settings?tab=' + key
}

// The open settings item: the tab in the URL when this person may open it, else the first one.
export function settingsTab(sections, tab) {
  const items = sections.flatMap(section => section.items).filter(item => item.key !== 'access')
  return (items.find(item => item.key === tab) || items[0])?.key || ''
}
