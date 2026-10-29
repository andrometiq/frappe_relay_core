import { onMounted, onBeforeUnmount } from 'vue'
import { subscribeRoom, onRealtime } from '../services/realtime'
import { realtimeRefreshQueue } from '../services/realtimeRefreshQueue'

// Refresh on the given realtime kinds, reconnects and a return to the tab. Returns the stop function.
export function watchRealtime(doctypes, kinds, refresh, delay) {
  const queue = realtimeRefreshQueue(refresh, () => document.visibilityState === 'visible', delay)
  function changed(event) {
    if (event?.kind === 'reconnect' || event?.kind === 'permissions' || kinds.includes(event?.kind)) queue.schedule(event.kind)
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
