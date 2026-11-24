import { reactive, ref } from 'vue'
import { coreApi } from './coreApi.js'
import { onRealtime } from './realtime.js'
import { setTheme } from './theme.js'

export const STATUSES = ['Available', 'Busy', 'Away', 'Do not disturb']
export const CLEAR_AFTER = [
  { value: '', label: "Don't clear" }, { value: '30m', label: '30 minutes' }, { value: '1h', label: '1 hour' },
  { value: '4h', label: '4 hours' }, { value: 'today', label: 'Today' }, { value: 'week', label: 'This week' },
]
export const myProfile = ref(null)

// Colleague cards for avatars, fetched in batches like linked titles and dropped when any profile changes.
// Profile events carry no user, so they only refresh cards; they never touch this user's theme or density.
const cards = reactive(new Map()), pending = new Set()
let timer, generation = 0
export function profilesChanged(event) {
  if (!['user_profiles', 'reconnect'].includes(event?.kind)) return
  generation++; clearTimeout(timer); timer = null; pending.clear(); cards.clear()
}
onRealtime(profilesChanged)

async function resolve() {
  timer = null
  const current = generation
  const batch = [...pending].slice(0, 100)
  for (const user of batch) pending.delete(user)
  try {
    const { items } = await coreApi('user_profiles.cards', { users: JSON.stringify(batch) })
    if (current !== generation) return
    for (const item of items) cards.set(item.user, item)
  } catch { /* An avatar without a card keeps its initials. */ }
  if (pending.size) timer = setTimeout(resolve, 0)
}

export function userCard(user) {
  if (!user || user === 'Guest') return null
  if (!cards.has(user)) {
    cards.set(user, null)
    pending.add(user)
    if (!timer) timer = setTimeout(resolve, 0)
  }
  return cards.get(user)
}

export function setDensity(density) {
  document.documentElement.dataset.density = String(density || 'Comfortable').toLowerCase()
}

// The one place a profile's theme and density reach the page.
export function applyPreferences({ theme, density } = {}) {
  if (theme) setTheme(theme.toLowerCase())
  if (density) setDensity(density)
}

// Save keeps only the theme and density the person previewed; an untouched one leaves the page as it is.
export function applyPreviewed(form, previewed) {
  applyPreferences({ theme: previewed.has('theme') && form.theme, density: previewed.has('density') && form.density })
}

export async function loadMyProfile() {
  myProfile.value = await coreApi('user_profiles.get')
  return myProfile.value
}

// On start the saved theme wins once it is set; the default System keeps this browser's own choice.
export async function loadStartPreferences() {
  const profile = await loadMyProfile()
  if (profile.theme !== 'System') setTheme(profile.theme.toLowerCase())
  setDensity(profile.density)
}

// The fields of a profile form that differ from the saved profile; unchanged fields, such as a photo, are not sent.
export function changedFields(form, saved) {
  return Object.fromEntries(Object.entries(form).filter(([key, value]) => key in saved && value !== saved[key]))
}

// Saves the given fields; only an explicit theme or density change applies to this page.
export async function saveMyProfile(values) {
  myProfile.value = await coreApi('user_profiles.update', values, true)
  applyPreferences({ theme: 'theme' in values && myProfile.value.theme, density: 'density' in values && myProfile.value.density })
  cards.delete(myProfile.value.user)
  return myProfile.value
}
