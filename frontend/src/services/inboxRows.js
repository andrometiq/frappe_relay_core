// Live inbox updates: fetch only conversations active since the newest loaded one, then move them to the top.
const activity = row => row.last_message_at || row.creation || ''

export function newestActivity(rows) {
  return rows.reduce((newest, row) => activity(row) > newest ? activity(row) : newest, '')
}

// Fresh rows reuse the shown row objects, so only changed values re-render.
function reuse(rows, fresh) {
  const shown = new Map(rows.map(row => [row.name, row]))
  return fresh.map(row => shown.has(row.name) ? Object.assign(shown.get(row.name), row) : row)
}

export function mergeChangedRows(rows, changed) {
  const names = new Set(changed.map(row => row.name))
  return [...reuse(rows, changed), ...rows.filter(row => !names.has(row.name))]
}

// A fresh first page over the shown rows. Loaded rows older than the page stay below it; a shown row within the
// page's range that the page no longer holds has left this view, such as a read chat in Unread.
export function mergeFirstPage(rows, page) {
  const fresh = reuse(rows, page.items)
  if (!page.next || !fresh.length) return fresh
  const names = new Set(fresh.map(row => row.name)), oldest = activity(fresh.at(-1))
  return [...fresh, ...rows.filter(row => !names.has(row.name) && activity(row) < oldest)]
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
