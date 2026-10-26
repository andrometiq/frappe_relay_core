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
