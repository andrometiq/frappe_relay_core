import { ref } from 'vue'
const media = window.matchMedia('(prefers-color-scheme: dark)')
const allowed = ['light', 'dark', 'system']
let stored
try { stored = localStorage.getItem('theme') } catch {}
const normalize = value => {
  const current=String(value||'').toLowerCase()
  return current==='automatic' ? 'system' : allowed.includes(current) ? current : ''
}
const site = document.documentElement.dataset.themeMode || document.documentElement.dataset.theme
export const theme = ref(normalize(stored) || normalize(site) || 'system')
function apply() {
  const resolved = theme.value === 'system' ? (media.matches ? 'dark' : 'light') : theme.value
  document.documentElement.dataset.theme = resolved
  document.documentElement.style.colorScheme = resolved
}
export function setTheme(value) {
  if (!allowed.includes(value)) return
  theme.value = value
  try { localStorage.setItem('theme', value === 'system' ? 'automatic' : value) } catch {}
  apply()
}
media.addEventListener('change', () => { if (theme.value === 'system') apply() })
window.addEventListener('storage', event => { if (event.key === 'theme') { theme.value=normalize(event.newValue)||'system';apply() } })
apply()

// Automatic -> Light -> Dark, as the account menu button cycles them.
export const THEME_LABELS = { system: ['monitor', 'Automatic'], light: ['sun', 'Light'], dark: ['moon', 'Dark'] }
export function cycleTheme() {
  setTheme(allowed[(allowed.indexOf(theme.value) + 1) % allowed.length])
}
