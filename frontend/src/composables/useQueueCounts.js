import { computed, onScopeDispose, shallowRef, unref, watch } from 'vue'
import { coreApi } from '../services/coreApi'
import { sharedQueueCounts } from '../services/queueCounts'
import { watchRealtime } from './useRealtimeRefresh'

// One live count per channel for the whole app; refetched on the inbox realtime events, never polled.
const acquire = sharedQueueCounts(
  params => coreApi('queue_counts.read', params),
  load => watchRealtime(['Relay Message', 'Relay Conversation Assignment'], ['messages', 'inbox', 'reads', 'permissions', 'contacts'], load),
)

export function useQueueCounts(medium) {
  const lease = shallowRef(null)
  watch(() => unref(medium), value => {
    lease.value?.release()
    lease.value = acquire(value)
  }, { immediate: true })
  onScopeDispose(() => lease.value?.release())
  return { counts: computed(() => lease.value.counts.value) }
}
