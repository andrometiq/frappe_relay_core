<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { Button } from '@relay/ui'
import { onRealtime } from '../services/realtime'
import { ticketNotice } from '../services/ticketForm'

const notices = ref([])
const timers = new Map()
let stop
function dismiss(id) {
  clearTimeout(timers.get(id)); timers.delete(id)
  notices.value = notices.value.filter(row => row.id !== id)
}
function show(event) {
  if (event?.kind !== 'ticket_notice') return
  const notice = ticketNotice(event)
  if (!notice) return
  dismiss(notice.id)
  notices.value = [...notices.value, notice].slice(-3)
  timers.set(notice.id, setTimeout(() => dismiss(notice.id), 10000))
}
onMounted(() => { stop = onRealtime(show) })
onBeforeUnmount(() => { stop?.(); for (const timer of timers.values()) clearTimeout(timer) })
</script>

<template>
  <div class="ticket-notices" aria-live="polite">
    <div v-for="notice in notices" :key="notice.id" class="ticket-notice" role="status">
      <div class="ticket-notice-copy"><strong>{{ notice.title }}</strong><span>{{ notice.text }}</span></div>
      <a class="v1-link" :href="notice.href" @click="dismiss(notice.id)">Open</a>
      <Button icon="x" variant="ghost" aria-label="Dismiss notification" @click="dismiss(notice.id)" />
    </div>
  </div>
</template>

<style scoped>
.ticket-notices { position:fixed; right:16px; bottom:16px; z-index:80; display:flex; flex-direction:column; gap:8px; max-width:calc(100vw - 32px); width:340px; pointer-events:none; }
.ticket-notice { pointer-events:auto; display:flex; align-items:center; gap:10px; padding:10px 12px; background:var(--surface-white); border:1px solid var(--outline-gray-2); border-radius:9px; box-shadow:0 10px 35px #0002; }
.ticket-notice-copy { flex:1; min-width:0; display:flex; flex-direction:column; gap:2px; font-size:12px; }
.ticket-notice-copy strong { font-weight:600; color:var(--ink-gray-8); }
.ticket-notice-copy span { color:var(--ink-gray-6); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
</style>
