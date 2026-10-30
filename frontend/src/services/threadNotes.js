const timeOf = row => {
  const value = new Date(String(row.sent_at || row.creation || '').replace(' ', 'T')).getTime()
  return Number.isNaN(value) ? null : value
}

// Internal notes sit between messages at their time, inside the loaded stretch of the chat.
// `more` and `newer` say older or newer messages are not loaded yet.
export function notesInThread(rows, notes, { more = false, newer = false } = {}) {
  const times = rows.map(timeOf).filter(time => time !== null), first = times[0], last = times.at(-1)
  const shown = notes.map(note => ({ name: note.name, creation: note.creation, note }))
    .filter(row => !row.note.deleted && timeOf(row) !== null
      && (!more || (first !== undefined && timeOf(row) >= first)) && (!newer || (last !== undefined && timeOf(row) <= last)))
  const result = []
  for (const row of rows) {
    const time = timeOf(row)
    while (time !== null && shown.length && timeOf(shown[0]) < time) result.push(shown.shift())
    result.push(row)
  }
  return [...result, ...shown]
}
