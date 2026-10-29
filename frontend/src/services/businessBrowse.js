// A path stores values, including the empty-string bucket. Field order is owned by the server.
export const rootBrowse = () => ({ doctype: '', path: [], record: '', recordLabel: '', unlinked: false, query: '' })

export function readBrowse(hash) {
  const params = new URLSearchParams(hash.split('?')[1] || '')
  let path
  try { path = JSON.parse(params.get('group_path') || '[]') } catch { path = [] }
  if (!Array.isArray(path) || path.length > 6 || path.some(value => typeof value !== 'string')) path = []
  return { doctype: params.get('group_type') || '', path, record: params.get('group_record') || '',
    recordLabel: params.get('group_title') || '', unlinked: params.get('group_unlinked') === '1', query: params.get('group_query') || '' }
}

export function browseRoute(base, state) {
  const params = new URLSearchParams()
  if (state.doctype) params.set('group_type', state.doctype)
  if (state.path.length) params.set('group_path', JSON.stringify(state.path))
  if (state.record) { params.set('group_record', state.record); params.set('group_title', state.recordLabel || state.record) }
  if (state.query) params.set('group_query', state.query)
  if (state.unlinked) params.set('group_unlinked', '1')
  return base + (params.size ? '?' + params : '')
}

export function enterBrowse(state, tile) {
  if (tile.kind === 'type') return { ...rootBrowse(), doctype: tile.doctype }
  if (tile.kind === 'group') return { ...state, path: [...state.path, tile.value], record: '', recordLabel: '' }
  if (tile.kind === 'unlinked') return { ...rootBrowse(), unlinked: true }
  return { ...state, record: tile.name, recordLabel: tile.label || tile.name }
}

export function browseCrumbs(state, fields = []) {
  const crumbs = [{ label: 'Business types', state: rootBrowse() }]
  if (state.unlinked) return [...crumbs, { label: 'Not linked', state }]
  if (state.doctype) crumbs.push({ label: state.doctype, state: { ...rootBrowse(), doctype: state.doctype } })
  state.path.forEach((value, index) => crumbs.push({ label: value || 'Not set', title: fields[index]?.label,
    state: { ...state, path: state.path.slice(0, index + 1), record: '', recordLabel: '' } }))
  if (state.record) crumbs.push({ label: state.recordLabel || state.record, state })
  return crumbs
}

export function tileCount(count, noun) {
  return `${count || 0} ${noun}${Number(count) === 1 ? '' : 's'}`
}

export function tileUnread(tile) {
  return Number(tile.kind === 'record' ? tile.unread : tile.unread_records) || 0
}
