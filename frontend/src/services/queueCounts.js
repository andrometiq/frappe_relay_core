// Inbox queue counts from queue_counts.read; tabs and the Inbox badge use the same label.
const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })

export const EMPTY_COUNTS = Object.freeze({ all: 0, mine: 0, unassigned: 0, unread: 0, unread_messages: 0 })

// Exact below 1000, compact above it (1.6K) so a tab never grows wider than its queue name.
export function countLabel(value) {
  const count = Number(value) || 0
  if (count <= 0) return ''
  return count < 1000 ? String(count) : compact.format(count)
}

export function queueCountParams(medium) {
  return medium && medium !== 'all' ? { medium } : {}
}
