import { onMounted, ref } from 'vue'
import { coreApi } from '../services/coreApi'
const identity = ref(null), busy = ref(false), error = ref('')
export function useWhatsAppIdentity({ immediate = true } = {}) {
  async function load() {
    if (busy.value) return
    busy.value = true; error.value = ''
    try {
      const result = await coreApi('whatsapp.execute', { operation: 'account.metadata' }, true)
      identity.value = { ...result.profile, updated: result.last_success, status: result.status }
    } catch (e) { error.value = e.message }
    finally { busy.value = false }
  }
  onMounted(() => { if (immediate && !identity.value) load() })
  return { identity, busy, error, load }
}
