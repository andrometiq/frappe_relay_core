// A path stores values, including the empty-string bucket, and the field of each value.
// The server drops a path whose fields no longer match the grouping configuration.
export const rootBrowse = () => ({ doctype: '', path: [], pathFields: [], record: '', recordLabel: '', unlinked: false, query: '' })

function stringList(value) {
  try { value = JSON.parse(value || '[]') } catch { return [] }
  return Array.isArray(value) && value.length <= 6 && value.every(item => typeof item === 'string') ? value : []
}

export function readBrowse(hash) {
  const params = new URLSearchParams(hash.split('?')[1] || '')
  return { doctype: params.get('group_type') || '', path: stringList(params.get('group_path')),
    pathFields: stringList(params.get('group_fields')), record: params.get('group_record') || '',
    recordLabel: params.get('group_title') || '', unlinked: params.get('group_unlinked') === '1', query: params.get('group_query') || '' }
}

export function browseRoute(base, state) {
  const params = new URLSearchParams()
  if (state.doctype) params.set('group_type', state.doctype)
  if (state.path.length) { params.set('group_path', JSON.stringify(state.path)); params.set('group_fields', JSON.stringify(state.pathFields)) }
  if (state.record) { params.set('group_record', state.record); params.set('group_title', state.recordLabel || state.record) }
  if (state.query) params.set('group_query', state.query)
  if (state.unlinked) params.set('group_unlinked', '1')
  return base + (params.size ? '?' + params : '')
}

export function enterBrowse(state, tile) {
  if (tile.kind === 'type') return { ...rootBrowse(), doctype: tile.doctype }
  // A level is entered once: a second click on a stale tile of the same field changes nothing.
  if (tile.kind === 'group') return state.pathFields.includes(tile.field) ? state
    : { ...state, path: [...state.path, tile.value], pathFields: [...state.pathFields, tile.field], record: '', recordLabel: '' }
  if (tile.kind === 'unlinked') return { ...rootBrowse(), unlinked: true }
  return { ...state, record: tile.name, recordLabel: tile.label || tile.name }
}

export function browseCrumbs(state, fields = []) {
  const crumbs = [{ label: 'Business types', state: rootBrowse() }]
  if (state.unlinked) return [...crumbs, { label: 'Not linked', state }]
  if (state.doctype) crumbs.push({ label: state.doctype, state: { ...rootBrowse(), doctype: state.doctype } })
  state.path.forEach((value, index) => crumbs.push({ label: value || 'Not set', title: fields[index]?.label,
    state: { ...state, path: state.path.slice(0, index + 1), pathFields: state.pathFields.slice(0, index + 1), record: '', recordLabel: '' } }))
  if (state.record) crumbs.push({ label: state.recordLabel || state.record, state })
  return crumbs
}

export const tileKey = tile => JSON.stringify([tile.kind, tile.doctype, tile.name, tile.value])

// Tiles are ordered by newest activity, so a record can move to a later page between requests.
export function appendTiles(items, rows) {
  const shown = new Set(items.map(tileKey))
  return [...items, ...rows.filter(row => !shown.has(tileKey(row)))]
}

export function tileCount(count, noun) {
  return `${count || 0} ${noun}${Number(count) === 1 ? '' : 's'}`
}

export function tileUnread(tile) {
  return Number(tile.kind === 'record' ? tile.unread : tile.unread_records) || 0
}

export function levelLabel(state, fields = []) {
  if (state.record || state.unlinked) return 'Contacts'
  if (!state.doctype) return 'Business types'
  return fields[state.path.length]?.label || state.doctype
}

export function searchLabel(state, fields = []) {
  if (state.record || state.unlinked) return 'Search name, number or email'
  return state.doctype ? 'Search ' + levelLabel(state, fields) : 'Search business types'
}
