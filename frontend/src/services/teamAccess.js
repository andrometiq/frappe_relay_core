// A team's business access: per business type, all records, picked groups of its first grouping field, or picked records.
export const ALL = 'All records'
export const GROUP = 'Group'
export const RECORD = 'Record'

// The modes a business type offers: groups first when it has a grouping field, records one by one, or all records.
export function accessModes(type) {
  return type?.grouping_fields?.length ? [GROUP, RECORD, ALL] : [RECORD, ALL]
}

// The grouping field that team groups use: the type's first one.
export function groupField(type) {
  return type?.grouping_fields?.[0] || ''
}

// Saved rows grouped by business type and access, in the order they first appear. Groups keep the grouping field they
// were picked under. A type saved with two kinds of access in Desk shows twice, so the manager can remove one.
export function teamDraft(team) {
  const types = new Map()
  for (const row of team?.business || []) {
    const key = row.business_doctype + '\n' + row.access
    if (!types.has(key)) types.set(key, { doctype: row.business_doctype, mode: row.access, values: [], groupingField: row.grouping_field || '' })
    if (row.access !== ALL) types.get(key).values.push(row.value)
  }
  return { name: team?.name || '', title: team?.title || '', members: [...(team?.members || [])], types: [...types.values()] }
}

// A new draft entry for a business type, or null when the team already has the type.
export function draftType(types, type) {
  if (!type || types.some(row => row.doctype === type.business_doctype)) return null
  return { doctype: type.business_doctype, mode: accessModes(type)[0], values: [], groupingField: groupField(type) }
}

// Groups picked under a grouping field the type no longer uses match nothing; the manager picks them again.
export function staleGroups(draft, type) {
  return draft.mode === GROUP && draft.values.length > 0 && draft.groupingField !== groupField(type)
}

// The rows teams.save stores. A type in a picking mode with nothing picked gives no rows.
export function businessRows(types) {
  return types.flatMap(type => type.mode === ALL
    ? [{ business_doctype: type.doctype, access: ALL, value: '' }]
    : type.values.map(value => ({ business_doctype: type.doctype, access: type.mode, value,
      ...(type.mode === GROUP ? { grouping_field: type.groupingField } : {}) })))
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
