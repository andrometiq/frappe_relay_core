import { watch } from 'vue'
import { sha256Hex } from '../services/crypto.js'

// Session storage keeps drafts local to this tab and signed-in user.
export function useStoredDraft(scope, read, write, defaults) {
  const initial = JSON.parse(JSON.stringify(read()))
  let active = '', restoring = false
  watch(scope, value => {
    active = value ? 'relay-draft-' + sha256Hex(value) : ''
    if (!active) return
    try {
      const saved = JSON.parse(sessionStorage.getItem(active) || 'null')
      restoring = true; write(saved || (defaults ? defaults() : initial))
    } catch { /* An unavailable store leaves the live draft usable. */ }
    finally { restoring = false }
  }, { immediate: true, flush: 'sync' })
  watch(read, value => {
    if (!active || restoring) return
    try { sessionStorage.setItem(active, JSON.stringify(value)) } catch { /* Keep the live draft. */ }
  }, { deep: true, flush: 'sync' })
  return () => { if (active) sessionStorage.removeItem(active) }
}
