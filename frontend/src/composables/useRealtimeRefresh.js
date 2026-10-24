import { onMounted, onBeforeUnmount } from 'vue'
import { subscribeRoom, onRealtime } from '../services/realtime'
import { realtimeRefreshQueue } from '../services/realtimeRefreshQueue'
export function useRealtimeRefresh(doctypes, kinds, refresh) {
  let off, leave=[]
  const queue = realtimeRefreshQueue(refresh, () => document.visibilityState === 'visible')
  function changed(event) {
    if (event?.kind === 'reconnect' || event?.kind === 'permissions' || kinds.includes(event?.kind)) queue.schedule(event.kind)
  }
  function visible() {
    if (document.visibilityState === 'visible') queue.schedule('visible')
  }
  onMounted(() => {
    off = onRealtime(changed)
    leave = doctypes.map(dt => subscribeRoom(dt))
    document.addEventListener('visibilitychange', visible)
  })
  onBeforeUnmount(() => {
    queue.dispose(); off?.(); leave.forEach(fn=>fn())
    document.removeEventListener('visibilitychange', visible)
  })
}
