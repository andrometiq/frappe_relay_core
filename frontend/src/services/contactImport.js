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
