import { channelCan, channelEnabled } from './enabledChannels.js'

// A nav item lists the api.capabilities flags it needs, such as configure or teams.
const gates = ['manage', 'configure', 'teams', 'billing']

export function navAllowed(item, capabilities) {
  return gates.every(gate => !item[gate] || Boolean(capabilities?.[gate])) && channelEnabled(capabilities, item.channel)
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
