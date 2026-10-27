// The site's WhatsApp numbers from api.capabilities whatsapp_numbers. Number tags, filters and pickers
// show only when a site has two or more numbers; a one-number site keeps the plain layout.

export function whatsappNumbers(capabilities) {
  return capabilities?.whatsapp_numbers || []
}

export function hasManyNumbers(capabilities) {
  return whatsappNumbers(capabilities).length > 1
}

// The short name of a number for tags, or '' when the channel is not one of the site's numbers.
export function numberName(capabilities, channel) {
  return whatsappNumbers(capabilities).find(row => row.name === channel)?.label || ''
}

// Number filter rows: All numbers, then each number with its conversation count from queue_counts.numbers.
export function numberFilterOptions(numbers, counts) {
  return [
    { value: '', label: 'All numbers', address: '', count: counts?.all ?? null },
    ...numbers.map(row => ({ value: row.name, label: row.label, address: row.address, count: counts?.numbers?.[row.name] ?? null })),
  ]
}

const hours = seconds => Math.max(1, Math.ceil(seconds / 3600))

// One "Send via" row from messaging.send_numbers: open window, closed window or no chat yet on that number.
// Closed and new numbers stay selectable; they can take an approved template only.
export function sendNumberChoice(item, defaultChannel) {
  const open = !!item.window?.open
  const left = open && Number.isFinite(item.window.remaining_seconds) ? `${hours(item.window.remaining_seconds)} h left` : ''
  const wrote = item.channel === defaultChannel && item.has_chat
  const status = !item.has_chat ? 'No chat yet · template only'
    : !open ? 'Window closed · template only'
      : [wrote ? 'Customer wrote here' : 'Window open', left].filter(Boolean).join(' · ')
  return { value: item.channel, label: item.label, address: item.address, status, templateOnly: !open, hasChat: !!item.has_chat }
}

// The number a reply goes out from: the staff's pick while it is still a number of the site, else the backend default.
export function effectiveNumber(items, picked, defaultChannel) {
  const names = (items || []).map(item => item.channel)
  if (picked && names.includes(picked)) return picked
  return names.includes(defaultChannel) ? defaultChannel : names[0] || ''
}

// The window hint of the chosen number, as the one-number composer shows it.
export function windowHint(item) {
  const seconds = item?.window?.remaining_seconds
  if (!item?.window?.open || !Number.isFinite(seconds)) return ''
  return `24 h window open · ${hours(seconds)} h left`
}
