// Provider codes such as PENDING_DELETION read as sentence case: "Pending deletion".
export function sentenceCase(value) {
  const text = String(value ?? '').replaceAll('_', ' ').trim().toLowerCase()
  return text.charAt(0).toUpperCase() + text.slice(1)
}
