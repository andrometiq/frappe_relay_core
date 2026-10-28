import { ref } from 'vue'
import { coreApi } from '../services/coreApi'
import { emptySettings } from '../services/ticketSettings'
import { watchRealtime } from './useRealtimeRefresh'

// One copy for the page: every screen reads it. It loads once, then a realtime change reloads it.
const settings = ref(emptySettings())
let loading = null
let stopWatching = null
let requestSequence = 0

const reload = () => load(true).catch(() => {})

function load(force = false) {
  if (!stopWatching) stopWatching = watchRealtime(['Relay Ticket'], ['tickets'], reload)
  if (force || !loading) {
    const generation = ++requestSequence
    loading = coreApi('ticket_settings.read').then(
      value => { if (generation === requestSequence) settings.value = value },
      error => { if (generation === requestSequence) loading = null; throw error })
  }
  return loading
}

export function useTicketSettings() {
  const apply = value => { ++requestSequence; settings.value = value; loading = Promise.resolve() }
  return { settings, load, apply }
}
