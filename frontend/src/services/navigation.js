import { channelCan, channelEnabled } from './enabledChannels.js'

// A nav item lists the api.capabilities flags it needs, such as configure or teams.
const gates = ['manage', 'configure', 'teams', 'billing', 'ai', 'skills', 'business_events', 'flows']

export function navAllowed(item, capabilities) {
  return gates.every(gate => !item[gate] || Boolean(capabilities?.[gate])) && channelEnabled(capabilities, item.channel)
}

// Desktop rail groups. Each group opens its first allowed page; a group with more pages shows them as tabs.
const RAIL = [
  { name: 'Chats', icon: 'message-square', pages: ['Messages'] },
  { name: 'Tickets', icon: 'ticket', pages: ['Tickets'] },
  { name: 'Contacts', icon: 'users', pages: ['Contacts'] },
  { name: 'WhatsApp', icon: 'message-circle', pages: ['WhatsApp'] },
  { name: 'Automation', icon: 'zap', pages: ['Business events', 'Flows', 'Skills'] },
  { name: 'Settings', icon: 'settings', pages: ['Settings', 'Teams', 'Activity'], bottom: true },
]

export function railGroups(pages) {
  return RAIL.map(group => ({ ...group, pages: group.pages.map(name => pages.find(page => page.name === name)).filter(Boolean) }))
    .filter(group => group.pages.length)
}

// WhatsApp section tabs, shared by the sidebar, the phone More sheet and the section's own tab bar.
const WHATSAPP_SECTIONS = [
  { name: 'templates', label: 'Templates', icon: 'layout', feature: 'templates' },
  { name: 'campaigns', label: 'Bulk campaigns', icon: 'megaphone', manage: true, feature: 'bulk_campaigns' },
  { name: 'forms', label: 'Forms', icon: 'file-text', manage: true, feature: 'forms' },
  { name: 'billing', label: 'Billing', icon: 'credit-card', billing: true },
]

export function whatsappSections(capabilities) {
  if (!channelEnabled(capabilities, 'WhatsApp')) return []
  return WHATSAPP_SECTIONS.filter(section => navAllowed(section, capabilities)
    && (!section.feature || channelCan(capabilities, 'WhatsApp', section.feature)))
}

// Templates is the default tab, so its own ?template= links stay unchanged.
export function whatsappRoute(section) {
  return section === 'templates' ? '#/whatsapp' : '#/whatsapp?tab=' + section
}
