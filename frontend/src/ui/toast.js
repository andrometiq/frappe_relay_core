const SHOW_MS = 3000
let region = null

// A short confirmation, such as "Saved", read out by screen readers and gone after three seconds.
export function toast(message, { tone = 'success' } = {}) {
  if (typeof document === 'undefined' || !message) return
  if (!region?.isConnected) {
    region = document.createElement('div')
    region.className = 'relay-toast-region'
    region.setAttribute('role', 'status')
    region.setAttribute('aria-live', 'polite')
    document.body.append(region)
  }
  const item = document.createElement('div')
  item.className = 'relay-toast relay-toast--' + tone
  item.textContent = message
  region.append(item)
  setTimeout(() => item.remove(), SHOW_MS)
}
