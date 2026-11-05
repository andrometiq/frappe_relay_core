import { onMounted, onBeforeUnmount } from 'vue'
import { subscribeRoom, onRealtime } from '../services/realtime'
import { realtimeRefreshQueue, scheduleEvent } from '../services/realtimeRefreshQueue'

// Refresh on the given realtime kinds, reconnects and a return to the tab. Returns the stop function.
export function watchRealtime(doctypes, kinds, refresh, delay) {
  const queue = realtimeRefreshQueue(refresh, () => document.visibilityState === 'visible', delay)
  function visible() {
    if (document.visibilityState === 'visible') queue.schedule('visible')
  }
  const off = onRealtime(event => scheduleEvent(queue, kinds, event))
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
