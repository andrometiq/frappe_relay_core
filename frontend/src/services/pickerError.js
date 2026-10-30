export function pickerError(label, saved = false) {
  return `Could not load ${saved ? 'the saved selection for ' : ''}${(label || 'choices').toLowerCase()}. Try again. If this continues, ask your administrator to check your access.`
}
