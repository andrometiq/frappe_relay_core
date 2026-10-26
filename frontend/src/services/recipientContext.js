export function resetRecipient(fields) {
  const defaults = { source: null, quoting: false, body: '', attachment: null, kind: 'text', latitude: '', longitude: '', contactName: '', phone: '', emoji: '👍', alsoVia: [] }
  for (const [key, value] of Object.entries(defaults)) fields[key].value = value
}
