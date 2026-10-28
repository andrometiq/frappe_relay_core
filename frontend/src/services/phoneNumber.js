// A bare phone number as a chat caption: "918549974206" -> "+91 85499 74206". Anything else gives "".
export function phoneCaption(value) {
  const text = typeof value === 'string' ? value.trim() : ''
  if (!/^\+?[0-9][0-9 ()-]{6,19}$/.test(text)) return ''
  const digits = text.replace(/\D/g, '')
  if (digits.length < 7 || digits.length > 15) return ''
  if (digits.length === 12 && digits.startsWith('91')) return `+91 ${digits.slice(2, 7)} ${digits.slice(7)}`
  if (digits.length === 10 && !text.startsWith('+')) return `${digits.slice(0, 5)} ${digits.slice(5)}`
  return '+' + digits
}
