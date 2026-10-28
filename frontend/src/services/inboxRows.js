// Live inbox updates: fetch only conversations active since the newest loaded one, then move them to the top.
export const CHANGED_ROW_KINDS = new Set(['messages', 'incoming'])

export function newestActivity(rows) {
  return rows.reduce((newest, row) => {
    const activity = row.last_message_at || row.creation || ''
    return activity > newest ? activity : newest
  }, '')
}

export function mergeChangedRows(rows, changed) {
  const names = new Set(changed.map(row => row.name))
  return [...changed, ...rows.filter(row => !names.has(row.name))]
}

export function onlyChangedRows(kinds) {
  return kinds.size > 0 && [...kinds].every(kind => CHANGED_ROW_KINDS.has(kind))
}

// Only a manager may link an unlinked chat; a business row is already linked.
export function canLinkRow(row, manage) {
  return row.kind !== 'business' && Boolean(row.unlinked) && Boolean(manage)
}

// Row menu actions. A business row stands for its newest chat, so it offers only the read state.
export function rowActionKeys(row, { folders = false, manage = false } = {}) {
  const chat = row.kind !== 'business'
  return [row.unread ? 'read' : 'unread', ...(chat ? ['star'] : []), ...(chat && folders ? ['move'] : []),
    ...(chat && folders && row.folder ? ['unfile'] : []), ...(canLinkRow(row, manage) ? ['link'] : [])]
}
