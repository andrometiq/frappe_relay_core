const MANAGER = 'This page needs the Relay Communication Manager role. Ask your Relay manager or system administrator to give it to you.'
const SWITCHED_OFF = feature => `${feature} are turned off for this site. A System Manager can turn them on in Settings, under Features.`

// Why a nav page is closed to this user and who can open it. Gates are checked in the same order the menu checks them.
const REASONS = [
  ['configure', () => 'This page needs the System Manager role. Ask your system administrator to give it to you.'],
  ['teams', capabilities => capabilities?.manage && !capabilities?.teams_enabled ? SWITCHED_OFF('Teams') : MANAGER],
  ['ai', () => SWITCHED_OFF('AI features')],
  ['flows', capabilities => capabilities?.manage ? SWITCHED_OFF('Automations') : MANAGER],
  ['skills', () => MANAGER], ['manage', () => MANAGER], ['business_events', () => MANAGER], ['billing', () => MANAGER],
]

export function deniedReason(item, capabilities) {
  const found = REASONS.find(([gate]) => item?.[gate] && !capabilities?.[gate])
  if (found) return found[1](capabilities)
  return item?.channel ? `${item.channel} is turned off for this site. Ask your system administrator.` : ''
}
