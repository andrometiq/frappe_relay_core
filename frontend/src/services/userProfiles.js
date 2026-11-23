import { reactive, ref } from 'vue'
import { coreApi } from './coreApi'
import { onRealtime } from './realtime'
import { setTheme } from './theme'

export const STATUSES = ['Available', 'Busy', 'Away', 'Do not disturb']
export const CLEAR_AFTER = [
  { value: '', label: "Don't clear" }, { value: '30m', label: '30 minutes' }, { value: '1h', label: '1 hour' },
  { value: '4h', label: '4 hours' }, { value: 'today', label: 'Today' }, { value: 'week', label: 'This week' },
]
export const myProfile = ref(null)

// Colleague cards for avatars, fetched in batches like linked titles and dropped when any profile changes.
const cards = reactive(new Map()), pending = new Set()
let timer, generation = 0
onRealtime(event => {
  if (!['user_profiles', 'reconnect'].includes(event?.kind)) return
  generation++; clearTimeout(timer); timer = null; pending.clear(); cards.clear()
  if (myProfile.value) loadMyProfile().catch(() => {})
})

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

// The profile theme wins once it is set; the default System keeps this browser's own choice.
export function applyPreferences(profile, { initial = false } = {}) {
  if (!initial || profile.theme !== 'System') setTheme(profile.theme.toLowerCase())
  document.documentElement.dataset.density = profile.density.toLowerCase()
}

export async function loadMyProfile(initial = false) {
  myProfile.value = await coreApi('user_profiles.get')
  applyPreferences(myProfile.value, { initial })
  return myProfile.value
}

export async function saveMyProfile(values) {
  myProfile.value = await coreApi('user_profiles.update', values, true)
  applyPreferences(myProfile.value)
  cards.delete(myProfile.value.user)
  return myProfile.value
}
