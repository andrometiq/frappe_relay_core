import { reactive } from 'vue'
import { coreApi } from './coreApi'
import { onRealtime } from './realtime'
import { readableName } from './recordTitle'

const titles = reactive(new Map()), pending = new Map()
let timer, generation = 0
onRealtime(event => {
  if (!['permissions', 'reconnect', 'contacts', 'teams'].includes(event?.kind)) return
  generation++; clearTimeout(timer); timer = null; pending.clear(); titles.clear()
})
async function resolve() {
  timer = null
  const current = generation
  const batch = [...pending.entries()].slice(0, 50)
  for (const [key] of batch) pending.delete(key)
  try {
    const result = await coreApi('display.titles', { records: JSON.stringify(batch.map(([, value]) => value)) })
    if (current !== generation) return
    for (const row of result.items) titles.set(JSON.stringify([row.doctype, row.name]), row.title)
  } catch { /* Permission changes and missing links retain a neutral caption. */ }
  if (pending.size) timer = setTimeout(resolve, 0)
}

export function linkedTitle(doctype, name, fallback = doctype || 'Record') {
  if (!doctype || !name) return fallback
  const key = JSON.stringify([doctype, name])
  if (!titles.has(key)) {
    titles.set(key, '')
    pending.set(key, { doctype, name })
    if (!timer) timer = setTimeout(resolve, 0)
  }
  const title = titles.get(key)
  // A provider/account fallback is not a channel title. Hide generated local
  // account run keys while preserving configured titles and normal account names.
  const caption = doctype === 'Relay Channel'
    ? title?.replace(/^(WhatsApp|Telegram|Email) · c\d+-\d{16,20}$/, '$1')
    : title
  return readableName(caption, fallback)
}
