// Coalesce invalidations without polling. Preserve events received while hidden
// or while a permission-checked refresh is still running. Message names that events carry are kept too.
export function realtimeRefreshQueue(refresh, visible, delay = 150) {
  const kinds = new Set(), messages = new Set()
  let timer, running = false, disposed = false
  function schedule(kind, names = []) {
    if (disposed) return
    if (kind) kinds.add(kind)
    for (const name of names) messages.add(name)
    if (!timer && !running && visible() && kinds.size) timer = setTimeout(flush, delay)
  }
  async function flush() {
    timer = null
    if (disposed || running || !visible() || !kinds.size) return
    const batch = new Set(kinds), changed = new Set(messages)
    kinds.clear(); messages.clear()
    running = true
    try { await refresh({ kinds: batch, messages: changed }) }
    catch { /* View errors remain visible; retry only on another event or reconnect. */ }
    finally { running = false; schedule() }
  }
  return { schedule, dispose() { disposed = true; clearTimeout(timer); kinds.clear(); messages.clear() } }
}

// True when a batch holds only delivery status changes, which change no list row, count or reply window.
export function isReceiptsOnly(kinds) {
  return kinds?.size > 0 && [...kinds].every(kind => kind === 'receipts')
}

// How a chat list answers a batch of live events: receipts change no row, reads change the open one,
// new messages move rows in place, and anything else reloads.
export function listRefresh(kinds) {
  const only = allowed => kinds?.size > 0 && [...kinds].every(kind => allowed.includes(kind))
  if (only(['receipts'])) return 'none'
  if (only(['receipts', 'reads', 'chats'])) return 'selected'
  if (only(['receipts', 'reads', 'chats', 'messages', 'incoming'])) return 'loaded'
  return 'reload'
}
