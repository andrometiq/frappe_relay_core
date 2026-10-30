import { readableName } from './recordTitle.js'

// Contact business links as contacts.set_links and contacts.set_primary expect them.
const sameLink = (left, right) => left?.doctype === right?.doctype && left?.name === right?.name

export function isPrimaryLink(primary, link) {
  return sameLink(primary, link)
}

export function linksWith(links, link) {
  return links.some(row => sameLink(row, link)) ? links : [...links, { doctype: link.doctype, name: link.name }]
}

export function linksWithout(links, link) {
  return links.filter(row => !sameLink(row, link))
}

// Switching the primary on marks this record; switching it off clears the mark.
export function primaryRequest(contact, link, on) {
  return on ? { contact, doctype: link.doctype, name: link.name } : { contact }
}

// Enabled business types the user may link, as select options.
export function businessTypeOptions(types) {
  return (types || []).filter(row => row.enabled).map(row => ({ value: row.business_doctype, label: row.label || row.business_doctype }))
}

// The links heading counts the records, or says there are none.
export function linksHeading(count) {
  return count ? `Linked to · ${count}` : 'Not linked yet'
}

// Always confirm the business type, including when only one is enabled.
export function linkHint() {
  return 'Choose the record type, then find the record. The chat then shows its name.'
}

// Icon tile for a linked record: parties are green buildings, deliveries purple trucks, other documents blue.
export function recordIcon(doctype) {
  if (/customer|supplier|company|lead|partner|party/i.test(doctype || '')) return { icon: 'building', tone: 'green' }
  if (/delivery|shipment|dispatch|packing|transport/i.test(doctype || '')) return { icon: 'truck', tone: 'purple' }
  return { icon: 'file-text', tone: 'blue' }
}

// Chat header chip for the other linked records: "+2 linked" next to the primary, "2 linked" without one.
export function linkedLabel(profile) {
  const count = Number(profile?.link_count) || 0, others = count - (profile?.primary ? 1 : 0)
  if (others < 1) return ''
  return `${profile?.primary ? '+' : ''}${others} linked`
}

// One search over every linkable type: each match is a choice whose value carries its type.
// Under its shown title it shows the record ID when they differ, and the type when several are searched, so records with one title stay apart.
// A type that fails is skipped; only when every type fails is the first error raised.
const SEPARATOR = '\u0000'

export async function searchLinkChoices(types, search) {
  const results = await Promise.allSettled(types.map(type => search(type.value)))
  if (results.length && results.every(result => result.status === 'rejected')) throw results[0].reason
  const limit = types.length > 1 ? 10 : 30
  return results.flatMap((result, index) => result.status === 'fulfilled'
    ? result.value.slice(0, limit).map(row => {
      const label = readableName(row.label || row.name, row.name)
      const description = [types.length > 1 && types[index].label, label !== row.name && row.name].filter(Boolean).join(' · ')
      return { value: types[index].value + SEPARATOR + row.name, label, ...(description ? { description } : {}) }
    })
    : [])
}

export function linkFromChoice(value) {
  const [doctype, ...name] = String(value || '').split(SEPARATOR)
  return { doctype, name: name.join(SEPARATOR) }
}
