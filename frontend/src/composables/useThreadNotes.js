import { ref, watch } from 'vue'
import { coreApi } from '../services/coreApi'
import { useRealtimeRefresh } from './useRealtimeRefresh'

// The latest internal notes of one chat, shown in its thread. Socket.IO note changes reload them.
export function useThreadNotes(contact) {
  const items = ref([])
  let generation = 0
  async function load() {
    const current = ++generation, name = contact.value
    if (!name) return
    try {
      const result = await coreApi('collaboration.comments', { contact: name })
      if (current === generation) items.value = result.items || []
    } catch {
      // The thread keeps its notes; the Internal notes panel shows load errors.
    }
  }
  watch(contact, () => { ++generation; items.value = []; load() }, { immediate: true })
  useRealtimeRefresh([], ['comments'], load)
  return { items, load }
}
