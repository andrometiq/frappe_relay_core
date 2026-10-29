export const MAX_SELECTED_MESSAGES = 50
export const selectableMessage = row => !!row?.name && !row._pending && !row.note

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
