// Coalesce invalidations without polling. Preserve events received while hidden
// or while a permission-checked refresh is still running.
export function realtimeRefreshQueue(refresh, visible, delay = 150) {
  const kinds = new Set()
  let timer, running = false, disposed = false
  function schedule(kind) {
    if (disposed) return
    if (kind) kinds.add(kind)
    if (!timer && !running && visible() && kinds.size) timer = setTimeout(flush, delay)
  }
  async function flush() {
    timer = null
    if (disposed || running || !visible() || !kinds.size) return
    const batch = new Set(kinds)
    kinds.clear()
    running = true
    try { await refresh({ kinds: batch }) }
    catch { /* View errors remain visible; retry only on another event or reconnect. */ }
    finally { running = false; schedule() }
  }
  return { schedule, dispose() { disposed = true; clearTimeout(timer); kinds.clear() } }
}
