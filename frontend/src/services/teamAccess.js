// A team's business access: per business type, all records, picked groups of its first grouping field, or picked records.
export const ALL = 'All records'
export const GROUP = 'Group'
export const RECORD = 'Record'

// The modes a business type offers: groups first when it has a grouping field, records one by one, or all records.
export function accessModes(type) {
  return type?.grouping_fields?.length ? [GROUP, RECORD, ALL] : [RECORD, ALL]
}

// Saved rows grouped by business type and access, in the order they first appear. A type saved with both groups and
// records (possible in Desk) keeps both entries.
export function teamDraft(team) {
  const types = new Map()
  for (const row of team?.business || []) {
    const key = row.business_doctype + '\n' + row.access
    if (!types.has(key)) types.set(key, { doctype: row.business_doctype, mode: row.access, values: [] })
    if (row.access !== ALL) types.get(key).values.push(row.value)
  }
  return { name: team?.name || '', title: team?.title || '', members: [...(team?.members || [])], types: [...types.values()] }
}

// The rows teams.save stores. A type in a picking mode with nothing picked gives no rows.
export function businessRows(types) {
  return types.flatMap(type => type.mode === ALL
    ? [{ business_doctype: type.doctype, access: ALL, value: '' }]
    : type.values.map(value => ({ business_doctype: type.doctype, access: type.mode, value })))
}

// One line per business type for the team list, such as "Customer: 3 groups".
export function accessSummary(business, label) {
  return business.map(row => {
    const name = label(row.business_doctype)
    if (row.all) return 'All ' + name
    const parts = [row.groups && plural(row.groups, 'group'), row.records && plural(row.records, 'record')].filter(Boolean)
    return name + ': ' + (parts.join(', ') || 'nothing picked')
  })
}

// A grouping field's caption from its fieldname, such as "Customer Group".
export function fieldLabel(fieldname) {
  return String(fieldname || '').replace(/_/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase())
}

function plural(count, noun) {
  return count + ' ' + noun + (count === 1 ? '' : 's')
}
