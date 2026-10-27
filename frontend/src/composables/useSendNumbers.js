import { computed, ref, watch } from 'vue'
import { coreApi } from '../services/coreApi'
import { objectValue } from '../components/messageContent'
import { effectiveNumber, hasManyNumbers, sendNumberChoice } from '../services/whatsappNumbers'
import { useRealtimeRefresh } from './useRealtimeRefresh'

export const sendNumbersKey = Symbol('Send numbers')

/** "Send via" numbers of the open WhatsApp chat on a site with several numbers.
 * The default is the number of the person's newest incoming message, read again on each new message event. */
export function useSendNumbers(state, capabilities) {
  const { source, selected, quoting, pinnedSource, viaNumber, pickNumber } = state
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
  useRealtimeRefresh([], ['messages'], load)

  // A quote or a chosen business contact sends from its own message; otherwise the pick, else the default.
  const current = computed(() => {
    if (quoting.value || (!viaNumber.value && source.value && source.value === pinnedSource.value)) return source.value?.channel || ''
    return effectiveNumber(items.value, viaNumber.value, defaultChannel.value)
  })
  const chosen = computed(() => items.value.find(item => item.channel === current.value) || null)
  const wroteTo = computed(() => items.value.find(item => item.channel === defaultChannel.value && item.has_chat) || null)
  const choices = computed(() => items.value.map(item => ({ ...sendNumberChoice(item, defaultChannel.value), inline: true })))

  return { active, items, current, chosen, wroteTo, choices, pick: pickNumber, load }
}
