export const contactColumns = ['Mobile', 'Email', 'Contact name', 'Business type', 'Business record']
export const importCount = (count, singular) => `${count} ${singular}${count === 1 ? '' : 's'}`
export function importState(result) {
  const counts = result?.counts || {}
  return {
    valid: (counts.created || 0) + (counts.linked || 0),
    skipped: counts.skipped || 0, errors: counts.errors || 0,
    rows: result?.rows || [], error: result?.error || '',
  }
}
export function importFileError(file) {
  if (!file || !/\.(xlsx|csv)$/i.test(file.name)) return 'Choose an Excel (.xlsx) or CSV file.'
  return file.size > 5 * 1024 * 1024 ? 'Choose a file smaller than 5 MB.' : ''
}
// The Contacts list filters of a browse state; search filters contacts only inside a record and in Not linked.
export function exportSearch(state) {
  const params = new URLSearchParams()
  if (state.doctype) params.set('business_type', state.doctype)
  if (state.record) params.set('business_name', state.record)
  if (state.unlinked) params.set('unlinked', '1')
  if ((state.record || state.unlinked) && state.query) params.set('query', state.query)
  return params.size ? '?' + params : ''
}
export function downloadName(disposition) {
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition || '')
  if (encoded) return decodeURIComponent(encoded[1])
  return /filename="?([^";]+)"?/i.exec(disposition || '')?.[1] || 'Relay contacts.xlsx'
}
