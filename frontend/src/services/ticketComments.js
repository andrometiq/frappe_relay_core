import { ref } from 'vue'
import { stableSubmission } from './submission.js'

// One ticket's comments. A live reload never re-enables Add comment or replaces a newer list.
export function ticketCommentsStore(api) {
  const comments = ref([]), error = ref(''), sending = ref(false)
  let ticket = '', generation = 0, reads = 0

  function open(name) {
    ticket = name; ++generation
    comments.value = []; error.value = ''; sending.value = false
    return load()
  }
  async function load() {
    const current = generation, read = ++reads
    try {
      const rows = await api('ticket_tags.comments', { name: ticket })
      if (current === generation && read === reads) comments.value = rows
    } catch (e) { if (current === generation) error.value = e.message }
  }
  async function add(body, mentions) {
    if (sending.value || !body.trim()) return false
    const current = generation, payload = { name: ticket, body, mentions }
    sending.value = true; error.value = ''
    try {
      const rows = await stableSubmission('relay-ticket-comment', payload,
        key => api('ticket_tags.add_comment', { ...payload, request_key: key }, true))
      if (current !== generation) return false
      ++reads; comments.value = rows
      return true
    } catch (e) {
      if (current === generation) error.value = e.message
      return false
    } finally { if (current === generation) sending.value = false }
  }
  return { comments, error, sending, open, load, add }
}
