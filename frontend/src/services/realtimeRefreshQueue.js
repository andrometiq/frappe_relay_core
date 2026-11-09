// Coalesce invalidations without polling. Preserve events received while hidden
// or while a permission-checked refresh is still running. Message names that events carry are kept too.
// A message change carries one `change` key in every room it reaches; `open` holds the keys that also came with
// message names, which only the rooms of an open conversation send. `unknown` is a message change without a key.
export function realtimeRefreshQueue(refresh, visible, delay = 150) {
  const kinds = new Set(), messages = new Set(), changes = new Set(), open = new Set()
  let timer, running = false, disposed = false, unknown = false
  function schedule(kind, names = [], change = null) {
    if (disposed) return
    if (kind) kinds.add(kind)
    for (const name of names) messages.add(name)
    if (kind === 'messages') {
      if (!change) unknown = true
      else { changes.add(change); if (names.length) open.add(change) }
    }
    if (!timer && !running && visible() && kinds.size) timer = setTimeout(flush, delay)
  }
  function clear() { kinds.clear(); messages.clear(); changes.clear(); open.clear(); unknown = false }
  async function flush() {
    timer = null
    if (disposed || running || !visible() || !kinds.size) return
    const batch = { kinds: new Set(kinds), messages: new Set(messages), changes: new Set(changes), open: new Set(open), unknown }
    clear()
    running = true
    try { await refresh(batch) }
    catch { /* View errors remain visible; retry only on another event or reconnect. */ }
    finally { running = false; schedule() }
  }
  return { schedule, dispose() { disposed = true; clearTimeout(timer); clear() } }
}

// Queue one live event for a view that lists `kinds`; an event of another kind is not the view's.
// A view that lists 'receipts' gets a delivery status change under that kind instead of 'messages'.
export function scheduleEvent(queue, kinds, event) {
  const kind = event?.receipt && kinds.includes('receipts') ? 'receipts' : event?.kind
  if (kind === 'reconnect' || kind === 'permissions' || kinds.includes(kind)) queue.schedule(kind, Array.isArray(event.messages) ? event.messages : [], event.change)
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
  if (only(['receipts', 'reads', 'chats', 'messages'])) return 'loaded'
  return 'reload'
}

// A list's live refresh while a page loads would replace the loaded pages. It is held, and runs once with every
// held kind when release() is called after the load. A refresh that a page load cancelled is held the same way.
export function heldRefresh(isLoading, refresh) {
  let held = null
  function hold(kinds) { if (isLoading()) held = new Set([...(held || []), ...(kinds || [])]) }
  return {
    hold,
    refresh(batch = {}) { return isLoading() ? hold(batch.kinds) : refresh(batch) },
    release() {
      if (!held) return
      const kinds = held
      held = null
      return refresh({ kinds })
    },
  }
}

// Where the message changes of a batch happened, for a chat list. When every change also came from the open
// conversation's room, only that row changed: 'own' when this browser sent every named message (the list already
// moved the row), else 'selected'. A change seen only in the shared room is elsewhere and reads the first page.
export function chatListRefresh(batch, isOwn) {
  const kind = listRefresh(batch.kinds)
  if (kind !== 'loaded' || batch.unknown || !batch.changes?.size || [...batch.changes].some(change => !batch.open.has(change))) return kind
  const sendsOnly = [...batch.kinds].every(name => name === 'messages' || name === 'receipts')
  return sendsOnly && batch.messages.size && [...batch.messages].every(isOwn) ? 'own' : 'selected'
}
