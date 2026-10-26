import { channelEnabled } from './enabledChannels.js'

// A nav item lists the api.capabilities flags it needs, such as configure or teams.
const gates = ['manage', 'configure', 'teams', 'billing']

export function navAllowed(item, capabilities) {
  return gates.every(gate => !item[gate] || Boolean(capabilities?.[gate])) && channelEnabled(capabilities, item.channel)
}
