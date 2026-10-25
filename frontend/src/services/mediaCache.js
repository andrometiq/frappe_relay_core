import { serverError } from './serverError.js'

// Received media stays in this tab for the session, so a bubble that scrolls back never downloads twice.
const SESSION_BYTES = 96 * 1024 * 1024
// Hub serves only a few media downloads per account at once; a full thread must not exhaust them.
const PARALLEL_DOWNLOADS = 2
const entries = new Map(), waiting = []
let storedBytes = 0, active = 0

export function mediaURL(message) {
  return '/api/method/relay_core.attachments.read?message=' + encodeURIComponent(message)
}

async function inTurn(work) {
  while (active >= PARALLEL_DOWNLOADS) await new Promise(resolve => waiting.push(resolve))
  active++
  try {
    return await work()
  } finally {
    active--
    waiting.shift()?.()
  }
}

async function download(source) {
  let response
  try {
    response = await fetch(source, { credentials: 'same-origin' })
  } catch {
    throw Object.assign(Error('Connection lost. Check the connection and try again.'), { retry: true })
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const fallback = response.status === 403 ? 'You do not have permission to open this media.' : 'Media could not be loaded.'
    throw Object.assign(Error(serverError(body, fallback)), { retry: ![403, 404, 410].includes(response.status) })
  }
  const blob = await response.blob()
  return { url: URL.createObjectURL(blob), type: blob.type, size: blob.size }
}

function evict() {
  for (const [source, entry] of entries) {
    if (storedBytes <= SESSION_BYTES || entries.size <= 1) return
    if (!entry.value) continue
    URL.revokeObjectURL(entry.value.url)
    storedBytes -= entry.value.size
    entries.delete(source)
  }
}

export function loadMedia(message) {
  const source = mediaURL(message)
  const known = entries.get(source)
  if (known) {
    entries.delete(source)
    entries.set(source, known)
    return known.promise
  }
  const entry = {}
  entry.promise = inTurn(() => download(source)).then(value => {
    entry.value = value
    storedBytes += value.size
    evict()
    return value
  }, error => {
    entries.delete(source)
    throw error
  })
  entries.set(source, entry)
  return entry.promise
}

export function formatBytes(size) {
  if (!Number.isFinite(size) || size <= 0) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  const power = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1)
  const value = size / 1024 ** power
  return (power && value < 10 ? value.toFixed(1) : Math.round(value)) + ' ' + units[power]
}
