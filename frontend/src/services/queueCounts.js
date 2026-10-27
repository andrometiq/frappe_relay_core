import { ref } from 'vue'

// Inbox queue counts from queue_counts.read; tabs and the Inbox badge use the same label.
const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })

export const EMPTY_COUNTS = Object.freeze({ all: 0, unread: 0, read: 0, unread_messages: 0 })

// Exact below 1000, compact above it (1.6K) so a tab never grows wider than its queue name.
export function countLabel(value) {
  const count = Number(value) || 0
  if (count <= 0) return ''
  return count < 1000 ? String(count) : compact.format(count)
}

// Inbox filters (channels, business record) narrow the counts the same way they narrow the list.
export function queueCountParams(medium, filters = {}) {
  return { ...(medium && medium !== 'all' ? { medium } : {}), ...filters }
}

// Views of the same channel share one count, one read and one live refresh until the last view releases it.
export function sharedQueueCounts(read, watchChanges) {
  const entries = new Map()
  function create(key, params) {
    const counts = ref({ ...EMPTY_COUNTS })
    let generation = 0
    async function load() {
      const ticket = ++generation
      try {
        const result = await read(params)
        if (ticket === generation) counts.value = { ...EMPTY_COUNTS, ...result }
      } catch {
        if (ticket === generation) counts.value = { ...EMPTY_COUNTS }
      }
    }
    const entry = { counts, users: 0, stop: watchChanges(load) }
    entries.set(key, entry)
    load()
    return entry
  }
  return function acquire(medium, filters) {
    const params = queueCountParams(medium, filters), key = JSON.stringify(params)
    const entry = entries.get(key) || create(key, params)
    entry.users++
    let released = false
    return {
      counts: entry.counts,
      release() {
        if (released) return
        released = true
        if (--entry.users) return
        entry.stop()
        entries.delete(key)
      },
    }
  }
}
