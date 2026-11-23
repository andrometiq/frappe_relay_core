import { computed, ref, watch } from 'vue'
import { coreApi } from '../services/coreApi'
import { objectValue } from '../components/messageContent'
import { hasManyNumbers } from '../services/whatsappNumbers'
import { useRealtimeRefresh } from './useRealtimeRefresh'
import { isReceiptsOnly } from '../services/realtimeRefreshQueue'

export const sendNumbersKey = Symbol('Send numbers')

/** The site's WhatsApp numbers for the open chat on a site with several numbers: where the person wrote, and the
 * number a new conversation starts from. Read again on each new message event. */
export function useSendNumbers(state, capabilities) {
  const { source, selected, quoting, pinnedSource } = state
  const items = ref([]), defaultChannel = ref('')
  const contact = computed(() => source.value?.relay_contact || selected.value || '')
  const context = computed(() => objectValue(source.value?.provider_context))
  const active = computed(() => hasManyNumbers(capabilities.value) && context.value.provider === 'WhatsApp' && !context.value.group_id && items.value.length > 1)
  let generation = 0

  async function load() {
    const person = contact.value, ticket = ++generation
    if (!person || !hasManyNumbers(capabilities.value)) { items.value = []; defaultChannel.value = ''; return }
    try {
      const result = await coreApi('messaging.send_numbers', { contact: person })
      if (ticket === generation) { items.value = result.items || []; defaultChannel.value = result.default || '' }
    } catch {
      if (ticket === generation) { items.value = []; defaultChannel.value = '' }
    }
  }
  watch(contact, load, { immediate: true })
  useRealtimeRefresh([], ['messages', 'receipts'], ({ kinds } = {}) => isReceiptsOnly(kinds) ? undefined : load())

  // A quote or a chosen message sends from its own number; otherwise the backend default.
  const current = computed(() => {
    if (quoting.value || (source.value && source.value === pinnedSource.value)) return source.value?.channel || ''
    return items.value.some(item => item.channel === defaultChannel.value) ? defaultChannel.value : items.value[0]?.channel || ''
  })
  const wroteTo = computed(() => items.value.find(item => item.channel === defaultChannel.value && item.has_chat) || null)

  return { active, contact, items, current, wroteTo, load }
}
