import { channelCan, channelEnabled } from './enabledChannels.js'

// A nav item lists the api.capabilities flags it needs, such as configure or teams.
const gates = ['manage', 'configure', 'teams', 'billing', 'ai', 'skills', 'knowledge', 'persona', 'events', 'business_events', 'flows']

export function navAllowed(item, capabilities) {
  return gates.every(gate => !item[gate] || Boolean(capabilities?.[gate])) && channelEnabled(capabilities, item.channel)
}

// Get started stays reachable after setup (Add another number) but leaves the menu once setup is finished.
export function navListed(item, capabilities) {
  return navAllowed(item, capabilities) && (!item.setup || Boolean(capabilities?.onboarding?.required))
}

// A System Manager opening /relay on a site that is not set up lands on Get started.
export function opensSetup(capabilities, initialPath) {
  return Boolean(capabilities?.configure && capabilities?.onboarding?.required) && ['', '/', '/messages'].includes(initialPath)
}

// Desktop rail groups. Each group opens its first allowed page; a group with more pages lists them in its section sidebar.
// Templates and Campaigns open WhatsApp section tabs; Campaigns shows only when its section is allowed.
// Settings draws its own sidebar (ownSidebar), so the shell adds none.
const RAIL = [
  { name: 'Get started', icon: 'play', pages: ['Setup'] },
  { name: 'Inbox', icon: 'inbox', pages: ['Messages'] },
  { name: 'Tickets', icon: 'ticket', pages: ['Tickets'] },
  { name: 'Contacts', icon: 'users', pages: ['Contacts'] },
  { name: 'Templates', icon: 'layout', pages: ['WhatsApp'], section: 'templates' },
  { name: 'Campaigns', icon: 'megaphone', pages: ['WhatsApp'], section: 'campaigns', needsSection: true },
  { name: 'Automation', icon: 'zap', pages: ['Channel automation', 'Business events', 'Flows', 'Skills', 'Knowledge', 'Persona', 'Events'] },
  { name: 'Reports', icon: 'chart-column', pages: ['Activity'] },
  { name: 'Settings', icon: 'settings', pages: ['Settings', 'Teams'], bottom: true, ownSidebar: true },
]

export function railGroups(pages, sections = []) {
  return RAIL.map(group => ({ ...group, pages: group.pages.map(name => pages.find(page => page.name === name)).filter(Boolean) }))
    .filter(group => group.pages.length && (!group.needsSection || sections.some(section => section.name === group.section)))
}

// The rail group that owns the open page; WhatsApp tabs other than Campaigns belong to Templates.
export function activeRailGroup(groups, view, section) {
  const owners = groups.filter(group => group.pages.some(page => page.name === view))
  return owners.find(group => group.section === section) || owners.find(group => !group.needsSection) || owners[0]
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
