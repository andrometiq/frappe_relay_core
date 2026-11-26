import { ref } from 'vue'

export const CHAT_TICKET_PREVIEW = 10
export const CHAT_TICKET_PAGE = 20

export const emptyChatTicketFilters = () => ({ statuses: [], assignedTo: '', ticketType: '', query: '' })

// The tickets.directory request for one chat's tickets. An empty filter is left out, so it means "any".
export function chatTicketRequest(contact, filters = emptyChatTicketFilters(), after = '', limit = CHAT_TICKET_PAGE) {
  const { statuses = [], assignedTo = '', ticketType = '', query = '' } = filters
  return {
    contact, limit,
    ...(statuses.length ? { ticket_status: JSON.stringify(statuses) } : {}),
    ...(assignedTo ? { assigned_to: assignedTo } : {}),
    ...(ticketType ? { ticket_type: ticketType } : {}),
    ...(query.trim() ? { query: query.trim() } : {}),
    ...(after ? { after } : {}),
  }
}

export const hasChatTicketFilters = filters => Object.values(filters).some(value => Array.isArray(value) ? value.length : String(value).trim())

// One chat's ticket pages: the newest open() or reload wins, and more() appends the next page once.
export function chatTicketsStore(api, limit = CHAT_TICKET_PAGE) {
  const items = ref([]), next = ref(null), busy = ref(false), error = ref('')
  let generation = 0, contact = '', filters = emptyChatTicketFilters(), paging = null

  async function load() {
    const current = ++generation
    paging = null; busy.value = true; error.value = ''
    try {
      const page = await api('tickets.directory', chatTicketRequest(contact, filters, '', limit))
      if (current === generation) { items.value = page.items; next.value = page.next }
    } catch (e) { if (current === generation) error.value = e.message }
    finally { if (current === generation) busy.value = false }
  }
  function more() {
    if (paging || !next.value || error.value) return paging
    const current = generation
    paging = api('tickets.directory', chatTicketRequest(contact, filters, next.value.after, limit)).then(page => {
      if (current !== generation) return
      items.value = [...items.value, ...page.items.filter(row => !items.value.some(item => item.name === row.name))]
      next.value = page.next
    }, e => { if (current === generation) error.value = e.message }).finally(() => { if (current === generation) paging = null })
    return paging
  }
  function open(name, values = emptyChatTicketFilters()) {
    contact = name; filters = values; items.value = []; next.value = null
    return load()
  }
  return { items, next, busy, error, open, load, more }
}
