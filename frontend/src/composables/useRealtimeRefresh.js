import { onMounted, onBeforeUnmount } from 'vue'
import { subscribeRoom, onRealtime } from '../services/realtime'
import { realtimeRefreshQueue } from '../services/realtimeRefreshQueue'

// Refresh on the given realtime kinds, reconnects and a return to the tab. Returns the stop function.
// A view that lists 'receipts' gets a delivery status change under that kind instead of 'messages'.
export function watchRealtime(doctypes, kinds, refresh, delay) {
  const queue = realtimeRefreshQueue(refresh, () => document.visibilityState === 'visible', delay)
  function changed(event) {
    const kind = event?.receipt && kinds.includes('receipts') ? 'receipts' : event?.kind
    if (kind === 'reconnect' || kind === 'permissions' || kinds.includes(kind)) queue.schedule(kind, Array.isArray(event.messages) ? event.messages : [], event.change)
  }
  function visible() {
    if (document.visibilityState === 'visible') queue.schedule('visible')
  }
  const off = onRealtime(changed)
  const leave = doctypes.map(dt => subscribeRoom(dt))
  document.addEventListener('visibilitychange', visible)
  return () => {
    queue.dispose(); off(); leave.forEach(fn => fn())
    document.removeEventListener('visibilitychange', visible)
  }
}

export function useRealtimeRefresh(doctypes, kinds, refresh, delay) {
  let stop
  onMounted(() => { stop = watchRealtime(doctypes, kinds, refresh, delay) })
  onBeforeUnmount(() => stop?.())
}
