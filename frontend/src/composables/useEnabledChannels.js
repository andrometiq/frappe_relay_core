import { inject, ref } from 'vue'
import { channelEnabled } from '../services/enabledChannels'

export function useEnabledChannels() {
  const capabilities = inject('relayCapabilities', ref({}))
  return provider => channelEnabled(capabilities.value, provider)
}
