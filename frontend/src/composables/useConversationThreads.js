import { computed, ref, watch } from 'vue'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from './useRealtimeRefresh'

/** Threads of the open chat or business record: one per contact endpoint on one of our channels.
 * Read once on open and again only on socket events, a reconnect or a return to the tab. */
export function useConversationThreads(state) {
  const { selected, businessType, businessName } = state
  const items = ref([]), loading = ref(false), error = ref(''), loadedScope = ref('')
  const scope = computed(() => businessName.value ? JSON.stringify([businessType.value, businessName.value]) : selected.value ? JSON.stringify([selected.value]) : '')
  let generation = 0

  async function load() {
    const current = scope.value, ticket = ++generation
    if (!current) { items.value = []; loadedScope.value = ''; return }
    loading.value = true
    try {
      const values = businessName.value ? { doctype: businessType.value, name: businessName.value } : { contact: selected.value }
      const result = await coreApi('conversation_threads.threads', values)
      if (ticket !== generation) return
      items.value = result.items || []
      error.value = ''
      loadedScope.value = current
    } catch (e) {
      if (ticket === generation) error.value = e.message
    } finally {
      if (ticket === generation) loading.value = false
    }
  }
  watch(scope, () => { items.value = []; loadedScope.value = ''; error.value = ''; load() }, { immediate: true })
  useRealtimeRefresh([], ['messages', 'reads', 'chats', 'contacts'], () => { if (scope.value) return load() })

  // True once the threads of the open conversation have arrived, so a caller can pick one.
  const ready = computed(() => !!scope.value && loadedScope.value === scope.value)
  return { items, loading, error, ready, load }
}
