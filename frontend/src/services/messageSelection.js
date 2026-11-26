import { messageData, templateParts } from '../components/messageContent.js'

export const MAX_SELECTED_MESSAGES = 50

// A text message without text, email or template shows nothing, so it is not a row to pick.
export function hasContent(row) {
  const data = messageData(row)
  return data.kind !== 'text' || !!String(data.text || '').trim() || !!data.email || !!templateParts(data)
}
export const selectableMessage = row => !!row?.name && !row._pending && !row.note && hasContent(row)

export function selectMessages(rows, selected, name, anchor, range = false) {
  const available = rows.filter(selectableMessage).map(row => row.name)
  if (!available.includes(name)) return selected
  const next = new Set(selected)
  if (range && available.includes(anchor)) {
    const [start, end] = [available.indexOf(anchor), available.indexOf(name)].sort((a, b) => a - b)
    for (const id of available.slice(start, end + 1)) next.add(id)
  } else if (next.has(name)) next.delete(name)
  else next.add(name)
  return next.size > MAX_SELECTED_MESSAGES ? selected : [...next]
}
