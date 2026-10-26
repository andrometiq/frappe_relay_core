import { ref, unref, watch } from 'vue'
import { coreApi } from '../services/coreApi'
import { EMPTY_COUNTS, queueCountParams } from '../services/queueCounts'
import { useRealtimeRefresh } from './useRealtimeRefresh'

// Live inbox queue counts; refetched on the inbox realtime events, never polled.
export function useQueueCounts(medium) {
  const counts = ref({ ...EMPTY_COUNTS })
  let generation = 0
  async function load() {
    const ticket = ++generation
    try {
      const result = await coreApi('queue_counts.read', queueCountParams(unref(medium)))
      if (ticket === generation) counts.value = { ...EMPTY_COUNTS, ...result }
    } catch {
      if (ticket === generation) counts.value = { ...EMPTY_COUNTS }
    }
  }
  watch(() => unref(medium), load, { immediate: true })
  useRealtimeRefresh(['Relay Message', 'Relay Conversation Assignment'], ['messages', 'inbox', 'reads', 'permissions', 'contacts'], load)
  return { counts, load }
}
