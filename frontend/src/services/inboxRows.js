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

// Read state request of a row. A business row names its record, so every chat of the row changes.
export function readStateRequest(row, read) {
  const target = row.kind === 'business' ? { business_doctype: row.doctype, business_name: row.record } : { contact: row.name }
  return { ...target, read: read ? 1 : 0 }
}

// Row menu actions. Star and folders belong to one chat, so a business row offers only the read state.
export function rowActionKeys(row, { folders = false, manage = false } = {}) {
  const chat = row.kind !== 'business'
  return [row.unread ? 'read' : 'unread', ...(chat ? ['star'] : []), ...(chat && folders ? ['move'] : []),
    ...(chat && folders && row.folder ? ['unfile'] : []), ...(canLinkRow(row, manage) ? ['link'] : [])]
}
