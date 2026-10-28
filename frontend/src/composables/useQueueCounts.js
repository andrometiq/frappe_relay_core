import { computed, onScopeDispose, shallowRef, unref, watch } from 'vue'
import { coreApi } from '../services/coreApi'
import { countLabel, sharedQueueCounts } from '../services/queueCounts'
import { watchRealtime } from './useRealtimeRefresh'

// One live count per medium and filter set for the whole app; refetched on the inbox realtime events, never polled.
const acquire = sharedQueueCounts(
  params => coreApi('queue_counts.read', params),
  load => watchRealtime(['Relay Message'], ['messages', 'inbox', 'reads', 'permissions', 'contacts'], load),
)

export function useQueueCounts(medium, filters = {}) {
  const lease = shallowRef(null)
  watch(() => [unref(medium), unref(filters)], ([value, params]) => {
    const previous = lease.value
    lease.value = acquire(value, params)
    previous?.release()
  }, { immediate: true })
  onScopeDispose(() => lease.value?.release())
  return { counts: computed(() => lease.value.counts.value) }
}

// The inbox list has one row per business record or uncovered chat; the Chats badge counts the same rows.
export const INBOX_ROWS = Object.freeze({ rows: 'business' })

export function useUnreadChats(medium) {
  const { counts } = useQueueCounts(medium, INBOX_ROWS)
  return computed(() => countLabel(counts.value.unread))
}
