import { objectValue } from '../messageContent.js'

// Lookups a thread render needs, built once when its rows change. A render of every bubble then costs one map
// lookup per row instead of a scan of all rows (with a JSON parse each) and a new date formatter per row.
const contexts = new WeakMap()
const dayFormat = new Intl.DateTimeFormat([], { day: 'numeric', month: 'long', year: 'numeric' })

// The provider context of a row, parsed once per row object.
export function contextOf(row) {
  if (!contexts.has(row)) contexts.set(row, objectValue(row.provider_context))
  return contexts.get(row)
}

export function timeOf(message) {
  const value = new Date((message.sent_at || message.creation || '').replace(' ', 'T'))
  return Number.isNaN(value.getTime()) ? null : value
}

export function dayLabel(date, today = new Date()) {
  if (!date) return ''
  const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1)
  if (date.toDateString() === today.toDateString()) return 'Today'
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday'
  return dayFormat.format(date)
}

// The day divider label of each row that starts a new day.
export function dayDividers(rows, today = new Date()) {
  const dividers = new Map()
  let previous
  for (const row of rows) {
    const day = dayLabel(timeOf(row), today)
    if (day && day !== previous) dividers.set(row.name, day)
    previous = day
  }
  return dividers
}

// The message a reply quotes: the first loaded row of the same chat endpoint with the quoted provider message ID.
export function quoteIndex(rows) {
  const key = (row, id) => row.channel + '\u0000' + row.sender_endpoint + '\u0000' + id
  const rowsById = new Map()
  for (const row of rows) {
    const id = String(contextOf(row).message_id || row.provider_id)
    if (!rowsById.has(key(row, id))) rowsById.set(key(row, id), row)
  }
  return message => {
    const reply = contextOf(message).reply_to_message_id
    return reply === undefined ? undefined : rowsById.get(key(message, String(reply)))
  }
}
